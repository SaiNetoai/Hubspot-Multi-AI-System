from loguru import logger
import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from GiNet_sdk.sdk import GiNetSDK
import traceback
import json
from langchain_core.tools import tool
from langchain_mistralai import ChatMistralAI
from langchain.pydantic_v1 import BaseModel, Field
from langgraph.prebuilt import create_react_agent, ToolNode
from HubspotClient import HubspotClient
from langgraph.checkpoint.postgres import PostgresSaver
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph, MessagesState, START, END
from langchain_core.runnables import RunnableMap, RunnableLambda
import re

# API library Initialization
app = Flask(__name__)
CORS(app)

load_dotenv()
# Create object to access CRM platform
crm = HubspotClient(os.getenv("HUBSPOT_API_KEY"))

# Create object to access GiNet platform
giNet_server_url = os.getenv('giNet_server_url')
giNet_username = os.getenv('giNet_username')
giNet_password = os.getenv('giNet_password')
logger.debug(f"giNet_server_url:{giNet_server_url}")
gi = GiNetSDK(giNet_server_url, giNet_username, giNet_password, agenticWorkflow=True)
logger.debug("after gi initialization")

# Get LLM details from GiNet
llmDetails = gi.get_llm_details()
logger.debug(f"llmDetails['api_key']: {llmDetails['api_key']}, model=llmDetails['model']:{llmDetails['model']}")

# Routing Agent
@tool("route-to-agent",description="Selects which downstream agent should handle the given user query", return_direct=True)
def route_to_agent_tool(query: str):
    """
    Determines which agent (hubspot_agent, analyze_campaign_performance, etc.)
    should be invoked for this user query.
    """
    return query

routing_tools = [route_to_agent_tool]

AGENT_NAMES = ["hubspot_agent", "analyze_campaign_performance",
               "optimize_lead_funnel", "engagement_strategy"]

routing_prompt = ChatPromptTemplate.from_messages([
    SystemMessage(content="""
You are the Routing Agent.  Your only job is to pick which one of the available tools
should handle the user’s request.  Do NOT perform any other work.  Return exactly one
tool name and pass the original user query into that tool.

Available tools:
  • hubspot_agent
      – CRM lookup: contacts, deals, campaigns, tasks, etc.
  • analyze_campaign_performance
      – Analyzes JSON campaign data and returns performance insights.
  • optimize_lead_funnel
      – Takes campaign/lead metrics and suggests conversion improvements.
  • engagement_strategy
      – Takes optimized insights and recommends audience engagement tactics.

When you reply, wrap your answer in a single call to “route-to-agent” and set its input
to the user’s original query.  Only return the tool name inside that call.
""".strip()),
    MessagesPlaceholder(variable_name="messages"),
    ("placeholder", "{agent_scratchpad}")
])

routing_model = ChatMistralAI(
    mistral_api_key=llmDetails["api_key"],
    model=llmDetails["model"]
).bind_tools(routing_tools)

llm_model = routing_prompt | routing_model

def call_routing_model(state: MessagesState):
    # Invoke the LLM to pick an agent
    return {"messages": [llm_model.invoke(state["messages"])]}

def should_route_continue(state: MessagesState):
    last = state["messages"][-1]
    # Continue to the tool node once the LLM has emitted a tool call
    return "route-to-agent" if last.tool_calls else END

router_graph = StateGraph(MessagesState)
router_graph.add_node("router", call_routing_model)
router_graph.add_node("route-to-agent", ToolNode(routing_tools))
router_graph.add_edge(START, "router")
router_graph.add_conditional_edges("router", should_route_continue, ["route-to-agent", END])
router_graph.add_edge("route-to-agent", END)
routing_workflow = router_graph.compile()


# HUBSPOT AGENT
# Create system message
system_message = """You are a professional CRM Assistant with access to Hubspot CRM data. Your purpose is to provide users with precise, relevant information from their CRM system and help them create new tasks and campaigns when needed.

When answering queries:
- Present only the information requested in a clean, structured format
- Do not explain which tools you are using or how you are retrieving the data
- Do not mention function names or code snippets in your responses
- If data is not available, simply state so without explaining technical details
- Use tables, bullet points, or other formatting to present data clearly when appropriate
- Only include information that actually exists in the CRM system
- Be concise and business-oriented in your communications

The user only wants to see the actual CRM data that answers their question, formatted in a professional way. They do not need to know how you obtained it or what steps you took.

When dealing with:
- Companies: provide relevant business details
- Contacts: present name, position, and contact information
- Deals: show name, amount, stage, and relevant dates
- Tasks: display description, status, priority, and due dates
- Campaigns: show name, status (ACTIVE/INACTIVE/PAUSED), start/end dates, budget, spend, goal, and audience

When creating tasks:
- For task creation, collect all necessary information (subject, priority, due date, etc.)
- Valid task statuses are: NOT_STARTED, IN_PROGRESS, COMPLETED
- Valid task priorities are: HIGH, MEDIUM, LOW
- Due dates should be in YYYY-MM-DD format
- Confirm to the user when the task has been created successfully
- You can associate tasks with a specific company when creating them

When creating campaigns:
- For campaign creation, collect the campaign name and other relevant details
- Valid campaign statuses include: ACTIVE, INACTIVE, PAUSED
- Campaigns are created as INACTIVE by default and can be activated later
- Start and end dates should be in YYYY-MM-DD format
- You can set campaign goals, target audience, budget, and notes
- Confirm to the user when the campaign has been created successfully

When dealing with campaigns:
- Show campaign status (ACTIVE/INACTIVE/PAUSED)
- Display campaign dates, budget, spending, goals, and target audience
- You can activate or deactivate campaigns directly through the system
- Campaign analytics show budget vs spend percentage and other key metrics
- Offer to create new campaigns or modify existing ones when relevant
"""

# Create prompt template
prompt = ChatPromptTemplate.from_messages([
    SystemMessage(content=system_message),
    MessagesPlaceholder(variable_name="messages"),
    HumanMessage(content="{query}"),
    HumanMessage(content="{chat_history}"),
    ("placeholder", "{agent_scratchpad}"),
])

# Company-related models and tools
class CompanyDetails(BaseModel):
    company_name: str = Field(description="Name of the customer company for which information is required")

@tool("get-companies-tool", return_direct=True)
def getCompanies():
    "Get a list of all company names available in the CRM"
    return crm.get_company_list()

@tool("get-company-details-tool", args_schema=CompanyDetails, return_direct=True)
def getCompanyDetails(company_name: str):
    "Get detailed information about a specific company by name"
    return crm.get_company_by_name(company_name)

@tool("get-contacts-by-company-tool", args_schema=CompanyDetails, return_direct=True)
def getContactsByCompany(company_name: str):
    "Get contacts associated with a specific company"
    return crm.get_emails(company_name)  # This method returns contacts for the company

@tool("get-deals-by-company-tool", args_schema=CompanyDetails, return_direct=True)
def getDealsByCompany(company_name: str):
    "Get deals associated with a specific company"
    customer_details = crm.get_customer_details(company_name)
    if "recent_orders" in customer_details:
        return {"deals": customer_details["recent_orders"], "company_name": company_name}
    return {"error": f"No deals found for company: {company_name}"}

# Campaign-related models and tools
class CampaignStatus(BaseModel):
    status: str = Field(description="Status of campaigns to retrieve (ACTIVE, INACTIVE, PAUSED, etc.)")

class CampaignName(BaseModel):
    campaign_name: str = Field(description="Name of the campaign to search for")

class CampaignId(BaseModel):
    campaign_id: str = Field(description="ID of the campaign to retrieve or modify")

class CreateCampaignInput(BaseModel):
    name: str = Field(description="Name of the campaign")
    status: str = Field(description="Status of the campaign (ACTIVE, INACTIVE, PAUSED, COMPLETED, IN_PROGRESS)", default="PLANNED")
    start_date: str = Field(description="Campaign start date in YYYY-MM-DD format", default=None)
    end_date: str = Field(description="Campaign end date in YYYY-MM-DD format", default=None)
    goal: str = Field(description="Campaign goal description", default=None)
    audience: str = Field(description="Target audience description", default=None)
    notes: str = Field(description="Campaign notes or description", default=None)
    currency_code: str = Field(description="Currency code (USD, EUR, GBP, etc.)", default="USD")

@tool("get-all-campaigns-tool", return_direct=True)
def getAllCampaigns():
    """Get all campaigns in the HubSpot CRM system"""
    logger.debug("=== GET ALL CAMPAIGNS TOOL CALLED ===")
    
    try:
        result = crm.get_campaigns()
        logger.debug(f"Raw result from crm.get_campaigns(): {result}")
        
        if "error" in result:
            logger.error(f"Error from crm.get_campaigns(): {result['error']}")
            return {"error": result["error"]}
        
        # Format the response for better readability
        if "results" in result and result["results"]:
            campaigns = []
            for i, campaign in enumerate(result["results"]):
                logger.debug(f"Processing campaign {i}: {campaign}")
                
                # Initialize campaign info with defaults
                campaign_info = {
                    "id": campaign.get("id", "N/A"),
                    "name": "N/A",
                    "status": "N/A", 
                    "start_date": "N/A",
                    "end_date": "N/A",
                    "goal": "N/A",
                    "audience": "N/A",
                    "budget": "N/A",
                    "spend": "N/A"
                }
                
                # Try to get properties
                if "properties" in campaign and campaign["properties"]:
                    props = campaign["properties"]
                    logger.debug(f"Campaign {i} properties: {props}")
                    
                    # Update with actual values if they exist
                    campaign_info.update({
                        "name": props.get("hs_name") or "N/A",
                        "status": props.get("hs_campaign_status") or "N/A",
                        "start_date": props.get("hs_start_date") or "N/A",
                        "end_date": props.get("hs_end_date") or "N/A",
                        "goal": props.get("hs_goal") or "N/A",
                        "audience": props.get("hs_audience") or "N/A",
                        "budget": props.get("hs_budget_items_sum_amount") or "N/A",
                        "spend": props.get("hs_spend_items_sum_amount") or "N/A",
                        "leads": props.get("hs_leads", "N/A"),  # 👈 Add this
                        "purchases": props.get("hs_purchases", "N/A")  # 👈 Optional"
                    })
                else:
                    logger.warning(f"Campaign {i} has no properties or empty properties")
                    # Try to get name from other possible locations
                    if "name" in campaign:
                        campaign_info["name"] = campaign["name"]
                
                campaigns.append(campaign_info)
            
            return {
                "campaigns": campaigns,
                "total": len(campaigns),
                "message": f"Found {len(campaigns)} campaigns"
            }
        else:
            logger.debug("No campaigns found in results")
            return {"message": "No campaigns found in your HubSpot account"}
    
    except Exception as e:
        logger.error(f"Exception in getAllCampaigns: {str(e)}")
        import traceback
        logger.error(f"Exception traceback: {traceback.format_exc()}")
        return {"error": f"Unexpected error in getAllCampaigns: {str(e)}"}

@tool("get-active-campaigns-tool", return_direct=True)
def getActiveCampaigns():
    """Get all active campaigns in the HubSpot CRM system"""
    result = crm.get_active_campaigns()
    
    if "error" in result:
        return {"error": result["error"]}
    
    # Format the response for better readability
    if "results" in result and result["results"]:
        campaigns = []
        for campaign in result["results"]:
            if "properties" in campaign:
                props = campaign["properties"]
                campaign_info = {
                    "id": campaign.get("id", "N/A"),
                    "name": props.get("hs_name", "N/A"),
                    "status": props.get("hs_campaign_status", "N/A"),
                    "start_date": props.get("hs_start_date", "N/A"),
                    "end_date": props.get("hs_end_date", "N/A"),
                    "budget": props.get("hs_budget_items_sum_amount", "N/A"),
                    "spend": props.get("hs_spend_items_sum_amount", "N/A")
                }
                campaigns.append(campaign_info)
        
        return {
            "active_campaigns": campaigns,
            "total": len(campaigns),
            "message": f"Found {len(campaigns)} active campaigns"
        }
    else:
        return {"message": "No active campaigns found in your HubSpot account"}

@tool("get-campaigns-by-status-tool", args_schema=CampaignStatus, return_direct=True)
def getCampaignsByStatus(status: str):
    """Get campaigns filtered by status (ACTIVE, INACTIVE, PAUSED, etc.)"""
    result = crm.get_campaigns_by_status(status)
    
    if "error" in result:
        return {"error": result["error"]}
    
    # Format the response for better readability
    if "results" in result and result["results"]:
        campaigns = []
        for campaign in result["results"]:
            if "properties" in campaign:
                props = campaign["properties"]
                campaign_info = {
                    "id": campaign.get("id", "N/A"),
                    "name": props.get("hs_name", "N/A"),
                    "status": props.get("hs_campaign_status", "N/A"),
                    "start_date": props.get("hs_start_date", "N/A"),
                    "end_date": props.get("hs_end_date", "N/A"),
                    "budget": props.get("hs_budget_items_sum_amount", "N/A"),
                    "spend": props.get("hs_spend_items_sum_amount", "N/A")
                }
                campaigns.append(campaign_info)
        
        return {
            "campaigns": campaigns,
            "status": status,
            "total": len(campaigns),
            "message": f"Found {len(campaigns)} campaigns with status '{status}'"
        }
    else:
        return {"message": f"No campaigns found with status '{status}'"}

@tool("get-campaign-by-id-tool", args_schema=CampaignId, return_direct=True)
def getCampaignById(campaign_id: str):
    """Get detailed information about a specific campaign by ID"""
    result = crm.get_campaign_by_id(campaign_id)
    
    if "error" in result:
        return {"error": result["error"]}
    
    # Format the response for better readability
    if "properties" in result:
        props = result["properties"]
        campaign_info = {
            "id": result.get("id", "N/A"),
            "name": props.get("hs_name", "N/A"),
            "status": props.get("hs_campaign_status", "N/A"),
            "start_date": props.get("hs_start_date", "N/A"),
            "end_date": props.get("hs_end_date", "N/A"),
            "goal": props.get("hs_goal", "N/A"),
            "audience": props.get("hs_audience", "N/A"),
            "notes": props.get("hs_notes", "N/A"),
            "budget": props.get("hs_budget_items_sum_amount", "N/A"),
            "spend": props.get("hs_spend_items_sum_amount", "N/A"),
            "owner": props.get("hs_owner", "N/A"),
            "color": props.get("hs_color_hex", "N/A")
        }
        
        return {
            "campaign": campaign_info,
            "message": f"Campaign details for '{campaign_info['name']}'"
        }
    else:
        return {"error": f"Campaign with ID {campaign_id} not found or has no properties"}

@tool("get-campaigns-by-name-tool", args_schema=CampaignName, return_direct=True)
def getCampaignsByName(campaign_name: str):
    """Search for campaigns by name (partial match supported)"""
    result = crm.get_campaigns_by_name(campaign_name)
    
    if "error" in result:
        return {"error": result["error"]}
    
    # Format the response for better readability
    if "results" in result and result["results"]:
        campaigns = []
        for campaign in result["results"]:
            if "properties" in campaign:
                props = campaign["properties"]
                campaign_info = {
                    "id": campaign.get("id", "N/A"),
                    "name": props.get("hs_name", "N/A"),
                    "status": props.get("hs_campaign_status", "N/A"),
                    "start_date": props.get("hs_start_date", "N/A"),
                    "end_date": props.get("hs_end_date", "N/A"),
                    "goal": props.get("hs_goal", "N/A"),
                    "budget": props.get("hs_budget_items_sum_amount", "N/A")
                }
                campaigns.append(campaign_info)
        
        return {
            "campaigns": campaigns,
            "search_term": campaign_name,
            "total": len(campaigns),
            "message": f"Found {len(campaigns)} campaigns matching '{campaign_name}'"
        }
    else:
        return {"message": f"No campaigns found matching '{campaign_name}'"}

@tool("activate-campaign-tool", args_schema=CampaignId, return_direct=True)
def activateCampaign(campaign_id: str):
    """Activate a campaign by setting its status to ACTIVE"""
    result = crm.activate_campaign(campaign_id)
    
    if "error" in result:
        return {"error": result["error"]}
    
    return {
        "campaign_id": campaign_id,
        "message": result.get("message", "Campaign activation completed"),
        "previous_status": result.get("previous_status", "Unknown"),
        "new_status": result.get("new_status", "ACTIVE")
    }

@tool("deactivate-campaign-tool", args_schema=CampaignId, return_direct=True)
def deactivateCampaign(campaign_id: str):
    """Deactivate a campaign by setting its status to INACTIVE"""
    result = crm.deactivate_campaign(campaign_id)
    
    if "error" in result:
        return {"error": result["error"]}
    
    return {
        "campaign_id": campaign_id,
        "message": result.get("message", "Campaign deactivation completed"),
        "previous_status": result.get("previous_status", "Unknown"),
        "new_status": result.get("new_status", "INACTIVE")
    }

@tool("get-campaign-analytics-tool", args_schema=CampaignId, return_direct=True)
def getCampaignAnalytics(campaign_id: str):
    """Get analytics for a specific campaign"""
    result = crm.get_campaign_analytics(campaign_id)
    
    if "error" in result:
        return {
            "error": result["error"],
            "message": "Campaign analytics retrieved from available campaign properties"
        }
    
    return {
        "campaign_id": campaign_id,
        "analytics": result.get("analytics", {}),
        "message": result.get("message", f"Analytics retrieved for campaign {campaign_id}")
    }

@tool("create-campaign-tool", args_schema=CreateCampaignInput, return_direct=True)
def createCampaign(name: str, status: str = "PLANNED", start_date: str = None, 
                  end_date: str = None, goal: str = None, audience: str = None, 
                  notes: str = None, currency_code: str = "USD"):
    """Create a new campaign in HubSpot CRM system"""
    
    logger.debug(f"=== CREATE CAMPAIGN TOOL CALLED ===")
    logger.debug(f"Parameters: name={name}, status={status}, start_date={start_date}, end_date={end_date}")
    
    campaign_data = {
        "name": name,
        "status": status,
        "start_date": start_date,
        "end_date": end_date,
        "goal": goal,
        "audience": audience,
        "notes": notes
    }
    
    # Create campaign
    response = crm.create_campaign(campaign_data)
    logger.debug(f"Campaign creation response: {response}")
    
    # Check for error in response
    if "error" in response:
        error_msg = f"Failed to create campaign: {response['error']}"
        logger.error(error_msg)
        return {"error": error_msg, "success": False}
    
    # Check for successful creation
    if "id" not in response:
        error_msg = "No campaign ID returned from HubSpot API"
        logger.error(error_msg)
        return {"error": error_msg, "success": False}
    
    # Success response
    result = {
        "success": True,
        "campaign_id": response["id"],
        "message": f"Campaign '{name}' created successfully with ID: {response['id']}",
        "campaign_details": {
            "name": name,
            "status": status,
            "id": response["id"],
            "start_date": start_date,
            "end_date": end_date,
            "goal": goal,
            "audience": audience
        }
    }
    
    logger.info(f"Campaign created successfully: {name} with ID: {response['id']}")
    return result

@tool("debug-campaign-api-tool", return_direct=True)
def debugCampaignAPI():
    """Debug campaign API access and permissions"""
    return crm.debug_campaign_api()

# Update tools list to include new task management tools
tools = [
    debugCampaignAPI,
    getCompanies,
    getCompanyDetails,
    getContactsByCompany,
    getDealsByCompany,
    getAllCampaigns,
    getActiveCampaigns,
    getCampaignsByStatus,
    getCampaignById,
    getCampaignsByName,
    activateCampaign,
    deactivateCampaign,
    getCampaignAnalytics,
    createCampaign,
]

@tool("analyze-campaign-performance", return_direct=True)
def analyze_campaign_performance(data: dict):
    """
    Analyzes given campaign performance data and returns insights and improvement suggestions.
    Input: A dictionary containing campaigns with fields like name, goal, leads/purchases, budget, and spend.
    """
    # Join into textual summary for the CAA model
    analysis_input = json.dumps(data, indent=2)
    return f"Analyze the following campaign data:\n{analysis_input}"

caa_tools = [analyze_campaign_performance]

caa_prompt = ChatPromptTemplate.from_messages([
    SystemMessage(content="""You are a Campaign Analytics Specialist.

You receive structured JSON campaign data and provide:
- Comparison of goals vs outcomes
- Budget efficiency analysis
- Segment performance highlights
- Improvement strategies

Use bullet points and business-focused language. Avoid technical terminology or code references."""),
    MessagesPlaceholder(variable_name="messages"),
    ("placeholder", "{agent_scratchpad}")
])

caa_tool_node = ToolNode(caa_tools)

caa_model_raw = ChatMistralAI(
    mistral_api_key=llmDetails["api_key"],
    model=llmDetails["model"]
).bind_tools(caa_tools)


def call_caa_model(state: MessagesState):
    return {"messages": [caa_model_raw.invoke(state["messages"])]}

def should_caa_continue(state: MessagesState):
    last = state["messages"][-1]
    return "caa_tools" if last.tool_calls else END

caa_graph = StateGraph(MessagesState)
caa_graph.add_node("caa_agent", call_caa_model)
caa_graph.add_node("caa_tools", caa_tool_node)
caa_graph.add_edge(START, "caa_agent")
caa_graph.add_conditional_edges("caa_agent", should_caa_continue, ["caa_tools", END])
caa_graph.add_edge("caa_tools", "caa_agent")
caa_workflow = caa_graph.compile()

# ESA Agent
@tool(
    "engagement_strategy",
    description="Generates audience engagement tactics based on optimized campaign and lead insights",
    return_direct=True
)
def engagement_strategy(data: dict):
    """
    Takes a dict of optimized campaign/lead insights and returns
    actionable audience engagement recommendations.
    """
    payload = json.dumps(data, indent=2)
    return f"Generate engagement strategies based on the following optimized insights:\n{payload}"

esa_tools = [engagement_strategy]

esa_prompt = ChatPromptTemplate.from_messages([
    SystemMessage(content="""
You are an Engagement Strategy Specialist.
You receive structured JSON optimized insights for a campaign and its lead funnel.
Provide actionable audience engagement tactics:
- Messaging channels and content recommendations
- Timing and frequency strategies
- Personalization techniques
- Measurement and follow-up suggestions

Use bullet points, business-focused language, and avoid technical jargon.
    """.strip()),
    MessagesPlaceholder(variable_name="messages"),
    ("placeholder", "{agent_scratchpad}")
])

esa_tool_node = ToolNode(esa_tools)

esa_model_raw = ChatMistralAI(
    mistral_api_key=llmDetails["api_key"],
    model=llmDetails["model"]
).bind_tools(esa_tools)

esa_llm= esa_prompt | esa_model_raw

def call_esa_model(state: MessagesState):
    return {"messages": [esa_llm.invoke(state["messages"])]}

def should_esa_continue(state: MessagesState):
    last = state["messages"][-1]
    return "esa_tools" if last.tool_calls else END

esa_graph = StateGraph(MessagesState)
esa_graph.add_node("esa_agent", call_esa_model)
esa_graph.add_node("esa_tools", esa_tool_node)
esa_graph.add_edge(START, "esa_agent")
esa_graph.add_conditional_edges("esa_agent", should_esa_continue, ["esa_tools", END])
esa_graph.add_edge("esa_tools", "esa_agent")
esa_workflow = esa_graph.compile()

# LOA Agent
@tool(
    "optimize_lead_funnel",
    description="Generates lead-funnel optimization strategies based on campaign insights",
    return_direct=True
)
def optimize_lead_funnel(data: dict):
    """
    Takes a dict with 'campaigns' and 'analysis' strings and returns
    actionable lead-conversion optimization recommendations.
    """
    payload = json.dumps(data, indent=2)
    return (
        "Provide lead-funnel optimization strategies based on the following\n"
        f"campaign insights:\n{payload}"
    )

loa_tools = [optimize_lead_funnel]

loa_prompt = ChatPromptTemplate.from_messages([
    SystemMessage(content="""
You are a Lead Optimization Specialist.
You receive structured JSON containing campaign data and analytical insights.
Your task is to recommend concrete, step-by-step strategies to improve the
lead conversion funnel. Focus on:
- Lead capture mechanisms
- Nurture workflows
- Conversion rate improvements
- CRM best-practices
Use bullet points and business-focused language—no code or technical jargon.
""".strip()),
    MessagesPlaceholder(variable_name="messages"),
    ("placeholder", "{agent_scratchpad}")
])

loa_model = ChatMistralAI(
    mistral_api_key=llmDetails["api_key"],
    model=llmDetails["model"]
).bind_tools(loa_tools)

loa_llm= loa_prompt | loa_model

loa_tool_node = ToolNode(loa_tools)

def call_loa_model(state: MessagesState):
    return {"messages": [loa_llm.invoke(state["messages"])]}

def should_loa_continue(state: MessagesState):
    last = state["messages"][-1]
    return "optimize_lead_funnel" if last.tool_calls else END

loa_graph = StateGraph(MessagesState)
loa_graph.add_node("loa_agent", call_loa_model)
loa_graph.add_node("loa_tools", loa_tool_node)
loa_graph.add_edge(START, "loa_agent")
loa_graph.add_conditional_edges("loa_agent", should_loa_continue, ["loa_tools", END])
# no back‐edge; terminate after one tool run:
loa_graph.add_edge("loa_tools", END)

loa_workflow = loa_graph.compile()

# Initialize tool node
tool_node = ToolNode(tools)

# Initialize model with tools
model_with_tools = ChatMistralAI(mistral_api_key=llmDetails["api_key"], model=llmDetails["model"]).bind_tools(tools)

# Setup for the model
# Workflow to manage state and tool calls
workflow = StateGraph(MessagesState)

# Define the two nodes we will cycle between
def should_continue(state: MessagesState):
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools"
    return END

def call_model(state: MessagesState):
    messages = state["messages"]
    response = model_with_tools.invoke(messages)
    return {"messages": [response]}

# Register nodes in the workflow
workflow.add_node("agent", call_model)
workflow.add_node("tools", tool_node)
workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", should_continue, ["tools", END])
workflow.add_edge("tools", "agent")

class JSONPostgresSaver(PostgresSaver):
    def _dump_metadata(self, metadata):
        """Override the metadata dumping method to ensure JSON compatibility"""
        # Convert any problematic objects to JSON-serializable format
        try:
            # Try to make it JSON serializable first
            json_metadata = json.loads(json.dumps(metadata, default=str))
            return json.dumps(json_metadata)
        except TypeError:
            # If that fails, do more aggressive conversion
            serializable_metadata = {}
            for key, value in metadata.items():
                try:
                    # Try to serialize each item individually
                    json.dumps(value)
                    serializable_metadata[key] = value
                except TypeError:
                    # Convert problematic values to strings
                    serializable_metadata[key] = str(value)
            return json.dumps(serializable_metadata)

# Function to get planning related queries for planning-copilot chat
@app.route('/api/crmAgent', methods=['POST'])
def crmHubspotChat():
    try:
        logger.debug("Inside Hubspot crmCoPilotChat")
        data = request.json
        query = data.get('user_query')
        conversation_id = data.get('conversation_id')
        logger.debug(f"user_query: {query}")

        routing_out = routing_workflow.invoke({
        "messages": [HumanMessage(content=query)]
        })
        last_msg = routing_out["messages"]
        agent_name = None
        for msg in last_msg:    
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                agent_name = msg.tool_calls[0].name
                break

        if not agent_name and last_msg:
            raw = last_msg[0].content or ""
            m = re.search(r'route-to-agent\(([^)]+)\)', raw)
            agent_name = m.group(1) if m else raw.strip()

        logger.info(f"Routing to agent: {agent_name}")

        if agent_name == "hubspot_agent":
            if gi.memory is not None:
                with gi.memory.connection() as conn:
                    checkpointer = JSONPostgresSaver(conn)
                    app_graph     = workflow.compile(checkpointer=checkpointer)

                    if query.lower() in ["quit", "exit"]:
                        return jsonify({"response": "Exiting conversation. Goodbye!"})

                    response = app_graph.invoke(
                        {"messages": [HumanMessage(content=query)]},
                        config={"configurable": {"thread_id": str(conversation_id)}}
                    )
                    conn.close()
            else:
                app_graph = workflow.compile(checkpointer=None)
                response  = app_graph.invoke(
                    {"messages": [HumanMessage(content=query)]},
                    config={"configurable": {"thread_id": str(conversation_id)}}
                )

            return jsonify({"response": response["messages"][-1].content})
        
        elif agent_name == "analyze_campaign_performance":
            logger.info("Routing campaign analysis to CAA agent")
            raw_data = crm.get_campaigns()
            if "results" not in raw_data:
                return Response("No campaign data found to analyze.", mimetype="text/plain")

            # 📋 Build campaigns list
            campaigns = []
            for c in raw_data["results"]:
                props = c.get("properties", {})
                campaigns.append({
                   "id":         c.get("id", "N/A"),
                   "name":       props.get("hs_name", "N/A"),
                   "goal":       props.get("hs_goal", "N/A"),
                   "status":     props.get("hs_campaign_status", "N/A"),
                   "start_date": props.get("hs_start_date", "N/A"),
                   "end_date":   props.get("hs_end_date", "N/A"),
                   "audience":   props.get("hs_audience", "N/A"),
                   "notes":      props.get("hs_notes", "N/A"),
                   "budget":     props.get("hs_budget_items_sum_amount", "N/A"),
                   "spend":      props.get("hs_spend_items_sum_amount", "N/A")
                })
            
            caa_in  = {"campaigns": campaigns}
            caa_out = caa_workflow.invoke({
                "messages": [HumanMessage(
                    content=f"Analyze the following campaign data:\n{json.dumps(caa_in, indent=2)}"
                )]
            })
            caa_text = caa_out["messages"][-1].content

            followup_prompt = (
                "You just performed a campaign analysis.  The user’s original request was:\n"
                f"  \"{query}\"\n\n"
                "Based on the analysis below, pick exactly one of these next steps:\n"
                "  • optimize_lead_funnel  (to get deeper conversion‐funnel recommendations)\n"
                "  • engagement_strategy   (to get audience‐engagement tactics)\n"
                "  • done                  (analysis complete—return the CAA output)\n\n"
                "Respond with a tool call in the form:\n"
                "  route-to-agent(<chosen_tool>)\n\n"
                "Analysis:\n"
                f"{caa_text}"
            )
            followup_out = routing_workflow.invoke({
                "messages": [HumanMessage(content=followup_prompt)]
            })
            next_msg = followup_out["messages"][-1]
            # extract the tool name exactly as before
            if hasattr(next_msg, "tool_calls") and next_msg.tool_calls:
                next_agent = next_msg.tool_calls[0].name
            else:
                next_agent = next_msg.content.split("(",1)[0]
        
            if next_agent == "optimize_lead_funnel":
                loa_in  = {"campaigns": campaigns, "analysis": caa_text}
                loa_out = loa_workflow.invoke({
                    "messages":[HumanMessage(content=json.dumps(loa_in, indent=2))]
                })
                loa_text = loa_out["messages"][-1].content

                # then pass into ESA
                esa_in  = {"campaigns": campaigns, "analysis": caa_text, "optimizations": loa_text}
                esa_out = esa_workflow.invoke({
                    "messages":[HumanMessage(
                        content=f"Generate engagement strategies based on these insights:\n{json.dumps(esa_in, indent=2)}"
                    )]
                })
                return Response(esa_out["messages"][-1].content, mimetype="text/plain")

            elif next_agent == "engagement_strategy":
                esa_in  = {"campaigns": campaigns, "analysis": caa_text}
                esa_out = esa_workflow.invoke({
                    "messages":[HumanMessage(
                        content=f"Generate engagement strategies based on these insights:\n{json.dumps(esa_in, indent=2)}"
                    )]
                })
                return Response(esa_out["messages"][-1].content, mimetype="text/plain")

            else:  # done
                return Response(caa_text, mimetype="text/plain")
        
        elif agent_name == "engagement_strategy":
            logger.info("Routing to Engagement Strategy (ESA) agent")
            raw_data = crm.get_campaigns()
            if "results" not in raw_data:
                return Response(
                    "No campaign data found to generate engagement strategies.",
                    mimetype="text/plain"
                )

            campaigns = []
            for c in raw_data["results"]:
                props = c.get("properties", {})
                campaigns.append({
                   "id":         c.get("id", "N/A"),
                   "name":       props.get("hs_name", "N/A"),
                   "goal":       props.get("hs_goal", "N/A"),
                   "status":     props.get("hs_campaign_status", "N/A"),
                   "start_date": props.get("hs_start_date", "N/A"),
                   "end_date":   props.get("hs_end_date", "N/A"),
                   "audience":   props.get("hs_audience", "N/A"),
                   "notes":      props.get("hs_notes", "N/A"),
                   "budget":     props.get("hs_budget_items_sum_amount", "N/A"),
                   "spend":      props.get("hs_spend_items_sum_amount", "N/A")
                })

            esa_in  = {"campaigns": campaigns}
            esa_out = esa_workflow.invoke({
                "messages": [HumanMessage(
                    content=f"Generate engagement strategies based on this campaign data:\n{json.dumps(esa_in, indent=2)}"
                )]
            })
            return Response(esa_out["messages"][-1].content, mimetype="text/plain")
        
        else:
            if gi.memory is not None:
                with gi.memory.connection() as conn:
                    checkpointer = JSONPostgresSaver(conn)
                    app_graph     = workflow.compile(checkpointer=checkpointer)
                    response      = app_graph.invoke(
                        {"messages": [HumanMessage(content=query)]},
                        config={"configurable": {"thread_id": str(conversation_id)}}
                    )
                    conn.close()
            else:
                app_graph = workflow.compile(checkpointer=None)
                response  = app_graph.invoke(
                    {"messages": [HumanMessage(content=query)]},
                    config={"configurable": {"thread_id": str(conversation_id)}}
                )

            return jsonify({"response": response["messages"][-1].content})

    except Exception as e:
        logger.error("Error occurred in crmHubspotChat: " + str(e))
        logger.error(traceback.format_exc())
        return structured_error_response("Failed", str(e)), 500


def structured_error_response(status, message):
    response = {}
    response['status']= status
    response['Error message']= message
    return response

# Register the workflow as chat capable
response = gi.register_chat_workflow(
    workflow_name="HubSpot Co-Pilot Test2", 
    base_url=f"{os.getenv('base_url')}/api/crmAgent", 
    workflow_type="chat", 
    description="This workflow creates a HubSpot Co-Pilot for enabling users to quickly get the details of pending tasks and actions from CRM",  
    document_name=None
)

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=2096)