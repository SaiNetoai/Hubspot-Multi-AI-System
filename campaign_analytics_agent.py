# campaign_analytics_agent.py
import os
import json
from loguru import logger
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS

from GiNet_sdk.sdk import GiNetSDK
from langchain_mistralai import ChatMistralAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode

app = Flask(__name__)
CORS(app)

# === Load Env & GiNet Setup ===
load_dotenv()
giNet_server_url = os.getenv('giNet_server_url')
giNet_username = os.getenv('giNet_username')
giNet_password = os.getenv('giNet_password')
logger.debug(f"giNet_server_url:{giNet_server_url}")

# Get LLM details from GiNet
gi = GiNetSDK(giNet_server_url, giNet_username, giNet_password, agenticWorkflow=True)
llmDetails = gi.get_llm_details()
logger.debug("LLM initialized.")

# === Prompt Template ===
system_message = """You are a Campaign Analytics Specialist.

You will receive:
- A natural language query asking for campaign analysis
- A list of campaign performance records (in JSON)

Your job:
- Summarize campaign goals vs. outcomes
- Highlight over- or under-performing metrics
- Analyze budget vs spend
- Suggest improvements for upcoming campaigns

Always format your output in clear bullet points or markdown tables.
Avoid mentioning tools or internal processing steps.
"""



prompt = ChatPromptTemplate.from_messages([
    SystemMessage(content=system_message),
    MessagesPlaceholder(variable_name="messages"),
    ("placeholder", "{agent_scratchpad}")
])

# === Tools (Mock) ===
@tool("get-campaign-performance", return_direct=True)
def get_campaign_performance():
    """Fetch performance metrics of recent campaigns (mocked)."""
    return {
        "campaigns": [
            {"name": "Spring Launch", "goal": "500 leads", "leads": 420, "budget": 1000, "spend": 890},
            {"name": "Winter Sale", "goal": "200 purchases", "purchases": 250, "budget": 800, "spend": 750}
        ]
    }

tools = [get_campaign_performance]

tool_node = ToolNode(tools)
model_with_tools = ChatMistralAI(
    mistral_api_key=llmDetails["api_key"],
    model=llmDetails["model"]
).bind_tools(tools)

def call_model(state: MessagesState):
    return {"messages": [model_with_tools.invoke(state["messages"])]}

def should_continue(state: MessagesState):
    return "tools" if state["messages"][-1].tool_calls else END

workflow = StateGraph(MessagesState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", tool_node)
workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", should_continue, ["tools", END])
workflow.add_edge("tools", "agent")

analytics_app = workflow.compile()

# === API Endpoint ===
@app.route('/api/campaign-analytics', methods=['POST'])
def campaign_analytics():
    try:
        data = request.json
        query = data.get("query", "")
        campaign_data = data.get("data", [])  # Expecting list of campaign dicts

        logger.debug(f"Received query: {query}")
        logger.debug(f"Campaign Data: {campaign_data}")

        combined_prompt = f"{query}\n\nHere is the campaign data:\n{json.dumps(campaign_data, indent=2)}"

        response = analytics_app.invoke({
            "messages": [HumanMessage(content=combined_prompt)]
        })

        return jsonify({"response": response['messages'][-1].content})

    except Exception as e:
        logger.error(f"Error during processing: {str(e)}")
        return jsonify({"error": str(e)}), 500


# === Run Standalone Server ===
if __name__ == "__main__":
    app.run(debug=True, port=5005)