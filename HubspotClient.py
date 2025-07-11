import requests
from loguru import logger
import traceback

class HubspotClient:
    """Client for interacting with the Hubspot API"""
    
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.hubapi.com"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def _make_request(self, method, endpoint, params=None, data=None):
        """Helper method to make API requests to Hubspot"""
        url = f"{self.base_url}/{endpoint}"
        
        try:
            logger.debug(f"Making {method} request to: {url}")
            logger.debug(f"Headers: {self.headers}")
            if params:
                logger.debug(f"Params: {params}")
            if data:
                logger.debug(f"Data: {data}")

            if method == "GET":
                response = requests.get(url, headers=self.headers, params=params)
            elif method == "POST":
                response = requests.post(url, headers=self.headers, json=data)
            elif method == "PUT":
                response = requests.put(url, headers=self.headers, json=data)
            elif method == "PATCH":
                response = requests.patch(url, headers=self.headers, json=data)
            else:
                return {"error": "Method not supported"}
            
            logger.debug(f"Response status code: {response.status_code}")
            logger.debug(f"Response content: {response.text}")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            error_msg = f"API request failed: {str(e)}"
            if hasattr(e.response, 'text'):
                error_msg += f"\nResponse: {e.response.text}"
            logger.error(error_msg)
            return {"error": error_msg}
    
    def get_companies(self, limit=10):
        """Get companies from Hubspot"""
        endpoint = "crm/v3/objects/companies"
        params = {
            "limit": limit,
            "properties": "name,domain,industry,phone,city,state,country,description"
        }
        return self._make_request("GET", endpoint, params=params)
    
    def get_company_list(self):
        """Get a simplified list of company names"""
        companies_data = self.get_companies(limit=100)
        if "results" in companies_data:
            return {
                "companies": [
                    company["properties"]["name"] 
                    for company in companies_data["results"] 
                    if "properties" in company and "name" in company["properties"]
                ]
            }
        return {"error": "Could not retrieve companies list"}
    
    def get_company_by_name(self, company_name):
        """Get company by name"""
        endpoint = "crm/v3/objects/companies/search"
        data = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "name",
                            "operator": "EQ",
                            "value": company_name
                        }
                    ]
                }
            ],
            "properties": ["name", "domain", "industry", "phone", "city", "state", "country", "description"],
            "limit": 1
        }
        return self._make_request("POST", endpoint, data=data)
    
    def get_contacts(self, limit=10):
        """Get contacts from Hubspot"""
        endpoint = "crm/v3/objects/contacts"
        params = {
            "limit": limit,
            "properties": "email,firstname,lastname,jobtitle,company,phone"
        }
        return self._make_request("GET", endpoint, params=params)
    
    def get_emails(self, company_name):
        """Get email contacts for a specific company"""
        contacts_data = self.get_contacts_by_company(company_name)
        if "contacts" in contacts_data and len(contacts_data["contacts"]) > 0:
            contact_list = []
            for contact in contacts_data["contacts"]:
                if "properties" in contact:
                    props = contact["properties"]
                    contact_info = {
                        "name": f"{props.get('firstname', '')} {props.get('lastname', '')}".strip(),
                        "email": props.get('email', 'N/A'),
                        "job_title": props.get('jobtitle', 'N/A'),
                        "phone": props.get('phone', 'N/A')
                    }
                    contact_list.append(contact_info)
            return {"company": company_name, "contacts": contact_list}
        return {"error": f"No contacts found for company: {company_name}"}
    
    def get_contacts_by_company(self, company_name):
        """Get contacts by company name"""
        # First get the company ID
        company_data = self.get_company_by_name(company_name)
        
        if "results" in company_data and len(company_data["results"]) > 0:
            company_id = company_data["results"][0]["id"]
            
            # Then get associated contacts
            endpoint = f"crm/v3/objects/companies/{company_id}/associations/contacts"
            associations = self._make_request("GET", endpoint)
            
            if "results" in associations and associations["results"]:
                # Get details for each contact
                contacts = []
                for assoc in associations["results"]:
                    contact_id = assoc["id"]
                    contact_endpoint = f"crm/v3/objects/contacts/{contact_id}"
                    params = {"properties": "email,firstname,lastname,jobtitle,company,phone"}
                    contact_data = self._make_request("GET", contact_endpoint, params=params)
                    contacts.append(contact_data)
                
                return {"contacts": contacts}
        
        return {"error": f"No contacts found for company: {company_name}"}
    
    def get_deals(self, limit=10):
        """Get deals from Hubspot"""
        endpoint = "crm/v3/objects/deals"
        params = {
            "limit": limit,
            "properties": "dealname,dealstage,amount,closedate,pipeline"
        }
        return self._make_request("GET", endpoint, params=params)
    
    def get_customer_details(self, company_name):
        """Get customer details including deals"""
        deals_data = self.get_deals_by_company(company_name)
        if "deals" in deals_data and len(deals_data["deals"]) > 0:
            formatted_deals = []
            for deal in deals_data["deals"]:
                if "properties" in deal:
                    props = deal["properties"]
                    deal_info = {
                        "name": props.get("dealname", "Unnamed Deal"),
                        "stage": props.get("dealstage", "Unknown"),
                        "amount": props.get("amount", "0"),
                        "close_date": props.get("closedate", "N/A")
                    }
                    formatted_deals.append(deal_info)
            return {"company": company_name, "recent_orders": formatted_deals}
        return {"error": f"No deals found for company: {company_name}"}
    
    def get_deals_by_company(self, company_name):
        """Get deals by company name"""
        # First get the company ID
        company_data = self.get_company_by_name(company_name)
        
        if "results" in company_data and len(company_data["results"]) > 0:
            company_id = company_data["results"][0]["id"]
            
            # Then get associated deals
            endpoint = f"crm/v3/objects/companies/{company_id}/associations/deals"
            associations = self._make_request("GET", endpoint)
            
            if "results" in associations and associations["results"]:
                # Get details for each deal
                deals = []
                for assoc in associations["results"]:
                    deal_id = assoc["id"]
                    deal_endpoint = f"crm/v3/objects/deals/{deal_id}"
                    params = {"properties": "dealname,dealstage,amount,closedate,pipeline"}
                    deal_data = self._make_request("GET", deal_endpoint, params=params)
                    deals.append(deal_data)
                
                return {"deals": deals}
        
        return {"error": f"No deals found for company: {company_name}"}
    
    def get_tasks(self, limit=10):
        """Get tasks from HubSpot CRM"""
        try:
            logger.debug("=== GETTING TASKS ===")
            endpoint = "crm/v3/objects/tasks"
            
            params = {
                "limit": limit,
                "properties": "hs_task_subject,hs_task_body,hs_task_status,hs_task_priority,hs_timestamp,hs_created_by_user_id"
            }
            
            logger.debug(f"Getting tasks with params: {params}")
            response = self._make_request("GET", endpoint, params=params)
            
            if "error" in response:
                logger.error(f"Get tasks failed: {response['error']}")
                return {"error": f"Failed to get tasks: {response['error']}"}
            
            logger.debug(f"Retrieved {len(response.get('results', []))} tasks")
            return response
            
        except Exception as e:
            logger.error(f"Exception in get_tasks: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    def get_tasks_by_status(self, status):
        """Get tasks filtered by status"""
        try:
            logger.debug(f"=== GETTING TASKS BY STATUS: {status} ===")
            endpoint = "crm/v3/objects/tasks/search"
            
            # Map status values
            status_mapping = {
                "NOT_STARTED": "NOT_STARTED",
                "IN_PROGRESS": "IN_PROGRESS",
                "COMPLETED": "COMPLETED"
            }
            hubspot_status = status_mapping.get(status.upper(), status)
            
            data = {
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "hs_task_status",
                                "operator": "EQ", 
                                "value": hubspot_status
                            }
                        ]
                    }
                ],
                "properties": ["hs_task_subject", "hs_task_body", "hs_task_status", "hs_task_priority", "hs_timestamp"],
                "limit": 20
            }
            
            response = self._make_request("POST", endpoint, data=data)
            
            if "error" in response:
                logger.error(f"Get tasks by status failed: {response['error']}")
                return {"error": f"Failed to get tasks by status: {response['error']}"}
            
            logger.debug(f"Found {len(response.get('results', []))} tasks with status {status}")
            return response
            
        except Exception as e:
            logger.error(f"Exception in get_tasks_by_status: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    def get_tasks_by_due_date(self, due_date):
        """Get tasks with specific due date"""
        try:
            logger.debug(f"=== GETTING TASKS BY DUE DATE: {due_date} ===")
            
            # Convert date to timestamp range for the entire day
            from datetime import datetime, timedelta
            if isinstance(due_date, str) and len(due_date) == 10:
                start_dt = datetime.strptime(due_date, "%Y-%m-%d")
                end_dt = start_dt + timedelta(days=1)
                
                start_timestamp = int(start_dt.timestamp() * 1000)
                end_timestamp = int(end_dt.timestamp() * 1000)
            else:
                return {"error": "Invalid date format. Use YYYY-MM-DD"}
            
            endpoint = "crm/v3/objects/tasks/search"
            data = {
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "hs_timestamp",
                                "operator": "GTE",
                                "value": str(start_timestamp)
                            },
                            {
                                "propertyName": "hs_timestamp", 
                                "operator": "LT",
                                "value": str(end_timestamp)
                            }
                        ]
                    }
                ],
                "properties": ["hs_task_subject", "hs_task_body", "hs_task_status", "hs_task_priority", "hs_timestamp"],
                "limit": 20
            }
            
            response = self._make_request("POST", endpoint, data=data)
            
            if "error" in response:
                logger.error(f"Get tasks by due date failed: {response['error']}")
                return {"error": f"Failed to get tasks by due date: {response['error']}"}
            
            logger.debug(f"Found {len(response.get('results', []))} tasks for date {due_date}")
            return response
            
        except Exception as e:
            logger.error(f"Exception in get_tasks_by_due_date: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    def create_task(self, task_data):
        """Create a new task in HubSpot CRM system - Fixed version"""
        try:
            logger.debug("=== CREATING TASK ===")
            logger.debug(f"Input task data: {task_data}")
            
            endpoint = "crm/v3/objects/tasks"
            
            # Start with required fields
            properties = {
                "hs_task_subject": task_data.get("subject")
            }
            
            # hs_timestamp is REQUIRED - set default if not provided
            if task_data.get("due_date"):
                due_date = task_data["due_date"]
                if isinstance(due_date, str) and len(due_date) == 10:  # YYYY-MM-DD format
                    from datetime import datetime
                    dt = datetime.strptime(due_date, "%Y-%m-%d")
                    properties["hs_timestamp"] = int(dt.timestamp() * 1000)
                    logger.debug(f"Due date: {due_date} -> {properties['hs_timestamp']}")
                else:
                    properties["hs_timestamp"] = due_date
            else:
                # Default to tomorrow if no due date provided
                from datetime import datetime, timedelta
                tomorrow = datetime.now() + timedelta(days=1)
                properties["hs_timestamp"] = int(tomorrow.timestamp() * 1000)
                logger.debug(f"Using default due date (tomorrow): {tomorrow}")
            
            # Add optional fields
            if task_data.get("body"):
                properties["hs_task_body"] = task_data["body"]
            
            if task_data.get("status"):
                status_mapping = {
                    "NOT_STARTED": "NOT_STARTED",
                    "IN_PROGRESS": "IN_PROGRESS", 
                    "COMPLETED": "COMPLETED",
                    "WAITING": "WAITING",
                    "DEFERRED": "DEFERRED"
                }
                hubspot_status = status_mapping.get(task_data["status"].upper(), "NOT_STARTED")
                properties["hs_task_status"] = hubspot_status
                logger.debug(f"Status: {task_data['status']} -> {hubspot_status}")
            else:
                properties["hs_task_status"] = "NOT_STARTED"  # Default status
            
            if task_data.get("priority"):
                priority_mapping = {
                    "HIGH": "HIGH",
                    "MEDIUM": "MEDIUM", 
                    "LOW": "LOW"
                }
                hubspot_priority = priority_mapping.get(task_data["priority"].upper(), "MEDIUM")
                properties["hs_task_priority"] = hubspot_priority
                logger.debug(f"Priority: {task_data['priority']} -> {hubspot_priority}")
            else:
                properties["hs_task_priority"] = "MEDIUM"  # Default priority
            
            data = {"properties": properties}
            logger.debug(f"Task creation payload: {data}")
            
            # Create the task
            response = self._make_request("POST", endpoint, data=data)
            logger.debug(f"Task creation response: {response}")
            
            if "error" in response:
                logger.error(f"Task creation failed: {response['error']}")
                return response
            
            # If task created successfully and company association requested
            if "id" in response and task_data.get("company_name"):
                task_id = response["id"]
                company_association = self.associate_task_with_company(task_id, task_data["company_name"])
                response["company_association"] = company_association
                logger.debug(f"Company association result: {company_association}")
            
            logger.info(f"Task created successfully with ID: {response.get('id')}")
            return response
            
        except Exception as e:
            logger.error(f"Exception in create_task: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": f"Unexpected error: {str(e)}"}

    def associate_task_with_company(self, task_id, company_name):
        """Associate a task with a company"""
        try:
            logger.debug(f"Associating task {task_id} with company {company_name}")
            
            # First, find the company by name
            company_data = self.get_company_by_name(company_name)
            
            if "results" in company_data and len(company_data["results"]) > 0:
                company_id = company_data["results"][0]["id"]
                logger.debug(f"Found company ID: {company_id}")
                
                # Create association
                endpoint = f"crm/v4/objects/tasks/{task_id}/associations/companies/{company_id}"
                assoc_data = {
                    "types": [
                        {
                            "associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": 214  # Task to Company association
                        }
                    ]
                }
                
                response = self._make_request("PUT", endpoint, data=assoc_data)
                
                if "error" not in response:
                    return {"success": True, "company_id": company_id}
                else:
                    logger.error(f"Association failed: {response['error']}")
                    return {"success": False, "error": response["error"]}
            else:
                return {"success": False, "error": f"Company '{company_name}' not found"}
                
        except Exception as e:
            logger.error(f"Error associating task with company: {str(e)}")
            return {"success": False, "error": str(e)}

    def get_tasks_by_company(self, company_name):
        """Get tasks by company name"""
        # First get the company ID
        company_data = self.get_company_by_name(company_name)
        
        if "results" in company_data and len(company_data["results"]) > 0:
            company_id = company_data["results"][0]["id"]
            
            # Then get associated tasks
            endpoint = f"crm/v3/objects/companies/{company_id}/associations/tasks"
            associations = self._make_request("GET", endpoint)
            
            if "results" in associations and associations["results"]:
                # Get details for each task
                tasks = []
                for assoc in associations["results"]:
                    task_id = assoc["id"]
                    task_endpoint = f"crm/v3/objects/tasks/{task_id}"
                    params = {"properties": "hs_task_subject,hs_task_status,hs_task_priority,hs_timestamp,hs_task_body"}
                    task_data = self._make_request("GET", task_endpoint, params=params)
                    tasks.append(task_data)
                
                return {"tasks": tasks}
        
        return {"error": f"No tasks found for company: {company_name}"}

    def debug_task_api(self):
        """Debug task API access and structure"""
        try:
            logger.debug("=== DEBUGGING TASK API ACCESS ===")
            
            # Test 1: Basic endpoint access
            endpoint = "crm/v3/objects/tasks"
            response = self._make_request("GET", f"{endpoint}?limit=1")
            logger.debug(f"Basic task endpoint test: {response}")
            
            # Test 2: Check available properties
            if "results" in response and len(response["results"]) > 0:
                sample_task = response["results"][0]
                logger.debug(f"Sample task structure: {sample_task}")
                if "properties" in sample_task:
                    available_props = list(sample_task["properties"].keys())
                    logger.debug(f"Available task properties: {available_props}")
            
            # Test 3: Try creating with minimal data
            test_data = {
                "properties": {
                    "hs_task_subject": "Test Task Debug"
                }
            }
            create_response = self._make_request("POST", endpoint, data=test_data)
            logger.debug(f"Minimal task creation test: {create_response}")
            
            return {
                "endpoint_access": response,
                "creation_test": create_response
            }
            
        except Exception as e:
            logger.error(f"Task debug error: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}

    def get_campaigns(self, limit=10):
        """Get campaigns from Hubspot Marketing API - Fixed to include properties"""
        try:
            logger.debug("=== GETTING CAMPAIGNS WITH PROPERTIES ===")
            endpoint = "marketing/v3/campaigns"
            
            # Request specific properties that we know exist
            params = {
                "limit": limit,
                "properties": "hs_name,hs_campaign_status,hs_start_date,hs_end_date,hs_goal,hs_audience,hs_notes"

            }
            
            logger.debug(f"Request: GET {endpoint}")
            logger.debug(f"Params: {params}")
            
            response = self._make_request("GET", endpoint, params=params)
            
            if "error" in response:
                logger.error(f"Error with properties request: {response['error']}")
                # Fallback: try without properties
                logger.debug("Trying fallback without properties...")
                params_fallback = {"limit": limit}
                response = self._make_request("GET", endpoint, params=params_fallback)
                
                if "error" in response:
                    logger.error(f"Fallback also failed: {response['error']}")
                    return {"error": f"Failed to get campaigns: {response['error']}"}
            
            # Log the structure of the first campaign to understand what we're getting
            if "results" in response and len(response["results"]) > 0:
                first_campaign = response["results"][0]
                logger.debug(f"First campaign structure: {first_campaign}")
                
                # Check if properties exist
                if "properties" in first_campaign:
                    logger.debug(f"Available properties: {list(first_campaign['properties'].keys())}")
                else:
                    logger.debug("No 'properties' key found in campaign")
                    
            logger.debug(f"Total campaigns retrieved: {len(response.get('results', []))}")
            return response
            
        except Exception as e:
            logger.error(f"Exception in get_campaigns: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": f"Unexpected error: {str(e)}"}
        
    def get_campaign_by_id(self, campaign_id):
        """Get campaign details by ID"""
        try:
            logger.debug(f"Attempting to get campaign with ID: {campaign_id}")
            endpoint = f"marketing/v3/campaigns/{campaign_id}"
            params = {
                "properties": "hs_name,hs_campaign_status,hs_start_date,hs_end_date,hs_goal,hs_audience,hs_notes,hs_owner,hs_budget_items_sum_amount,hs_spend_items_sum_amount,hs_color_hex,hs_currency_code,hs_created_by_user_id,hs_object_id"
            }
            response = self._make_request("GET", endpoint, params=params)
            
            if "error" in response:
                logger.error(f"Error getting campaign: {response['error']}")
                return {"error": f"Failed to get campaign: {response['error']}"}
            
            logger.debug(f"Successfully retrieved campaign: {response}")
            return response
        except Exception as e:
            logger.error(f"Unexpected error in get_campaign_by_id: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    def get_campaigns_by_status(self, status):
        """Get campaigns filtered by status - client-side filtering with correct status values"""
        try:
            logger.debug(f"Attempting to get campaigns with status: {status}")
            
            # Map common status terms to HubSpot's actual values
            status_mapping = {
                'ACTIVE': 'active',
                'INACTIVE': 'planned',  # Use 'planned' as default inactive state
                'PAUSED': 'paused',
                'COMPLETED': 'completed',
                'IN_PROGRESS': 'in_progress',
                'PLANNED': 'planned'
            }
            
            # Convert to HubSpot's expected format
            hubspot_status = status_mapping.get(status.upper(), status.lower())
            
            # Get all campaigns first
            all_campaigns = self.get_campaigns(limit=100)
            
            if "error" in all_campaigns:
                return all_campaigns
            
            # Filter campaigns by status client-side
            filtered_campaigns = []
            if "results" in all_campaigns:
                for campaign in all_campaigns["results"]:
                    if "properties" in campaign:
                        campaign_status = campaign["properties"].get("hs_campaign_status", "")
                        if campaign_status.lower() == hubspot_status.lower():
                            filtered_campaigns.append(campaign)
            
            result = {
                "results": filtered_campaigns,
                "total": len(filtered_campaigns)
            }
            
            logger.debug(f"Successfully filtered campaigns by status: {result}")
            return result
        except Exception as e:
            logger.error(f"Unexpected error in get_campaigns_by_status: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    def get_campaigns_by_name(self, campaign_name):
        """Get campaigns filtered by name - client-side filtering"""
        try:
            logger.debug(f"Attempting to get campaigns with name: {campaign_name}")
            
            # Get all campaigns first
            all_campaigns = self.get_campaigns(limit=100)
            
            if "error" in all_campaigns:
                return all_campaigns
            
            # Filter campaigns by name client-side (case-insensitive partial match)
            filtered_campaigns = []
            if "results" in all_campaigns:
                for campaign in all_campaigns["results"]:
                    if "properties" in campaign:
                        campaign_name_prop = campaign["properties"].get("hs_name", "")
                        if campaign_name.lower() in campaign_name_prop.lower():
                            filtered_campaigns.append(campaign)
            
            result = {
                "results": filtered_campaigns,
                "total": len(filtered_campaigns)
            }
            
            logger.debug(f"Successfully filtered campaigns by name: {result}")
            return result
        except Exception as e:
            logger.error(f"Unexpected error in get_campaigns_by_name: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    def get_active_campaigns(self):
        """Get campaigns with 'active' status"""
        try:
            logger.debug("Attempting to get active campaigns")
            return self.get_campaigns_by_status("active")
        except Exception as e:
            logger.error(f"Unexpected error in get_active_campaigns: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    def get_campaign_analytics(self, campaign_id):
        """Get analytics for a specific campaign"""
        try:
            logger.debug(f"Attempting to get analytics for campaign with ID: {campaign_id}")
            
            # Get campaign details which include budget/spend information
            campaign_details = self.get_campaign_by_id(campaign_id)
            
            if "error" in campaign_details:
                return campaign_details
            
            # Extract available analytics from campaign properties
            if "properties" in campaign_details:
                props = campaign_details["properties"]
                analytics = {
                    "campaign_id": campaign_id,
                    "name": props.get("hs_name", "N/A"),
                    "status": props.get("hs_campaign_status", "N/A"),
                    "budget": props.get("hs_budget_items_sum_amount", "N/A"),
                    "spend": props.get("hs_spend_items_sum_amount", "N/A"),
                    "start_date": props.get("hs_start_date", "N/A"),
                    "end_date": props.get("hs_end_date", "N/A"),
                    "goal": props.get("hs_goal", "N/A"),
                    "audience": props.get("hs_audience", "N/A"),
                    "currency": props.get("hs_currency_code", "N/A")
                }
                
                # Calculate spend percentage if both budget and spend are available
                try:
                    budget = float(props.get("hs_budget_items_sum_amount", 0) or 0)
                    spend = float(props.get("hs_spend_items_sum_amount", 0) or 0)
                    if budget > 0:
                        analytics["spend_percentage"] = round((spend / budget) * 100, 2)
                    else:
                        analytics["spend_percentage"] = 0
                except (ValueError, TypeError):
                    analytics["spend_percentage"] = "N/A"
                
                return {
                    "analytics": analytics,
                    "message": "Campaign analytics retrieved successfully"
                }
            
            return {"error": "Unable to retrieve campaign analytics"}
            
        except Exception as e:
            logger.error(f"Unexpected error in get_campaign_analytics: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    def update_campaign_status(self, campaign_id, status):
        """Update campaign status with correct HubSpot status values"""
        try:
            logger.debug(f"Attempting to update campaign {campaign_id} status to: {status}")
            
            # Map common status terms to HubSpot's actual values
            status_mapping = {
                'ACTIVE': 'active',
                'INACTIVE': 'planned',
                'PAUSED': 'paused',
                'COMPLETED': 'completed',
                'IN_PROGRESS': 'in_progress',
                'PLANNED': 'planned'
            }
            
            # Convert to HubSpot's expected format
            hubspot_status = status_mapping.get(status.upper(), status.lower())
            
            endpoint = f"marketing/v3/campaigns/{campaign_id}"
            data = {
                "properties": {
                    "hs_campaign_status": hubspot_status
                }
            }
            response = self._make_request("PATCH", endpoint, data=data)
            
            if "error" in response:
                logger.error(f"Error updating campaign status: {response['error']}")
                return {"error": f"Failed to update campaign status: {response['error']}"}
            
            logger.debug(f"Successfully updated campaign status: {response}")
            return response
        except Exception as e:
            logger.error(f"Unexpected error in update_campaign_status: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    def activate_campaign(self, campaign_id):
        """Activate a campaign by setting status to 'active'"""
        try:
            logger.debug(f"Attempting to activate campaign with ID: {campaign_id}")
            
            # First, get the campaign details to check current status
            campaign = self.get_campaign_by_id(campaign_id)
            
            if "error" in campaign:
                return campaign
            
            if "properties" in campaign:
                current_status = campaign["properties"].get("hs_campaign_status", "unknown")
                
                if current_status == "active":
                    return {
                        "message": f"Campaign {campaign_id} is already active",
                        "status": current_status,
                        "campaign_id": campaign_id
                    }
                
                # Try to update status to active
                update_result = self.update_campaign_status(campaign_id, "active")
                
                if "error" in update_result:
                    return {
                        "message": f"Could not activate campaign {campaign_id}. {update_result['error']}",
                        "status": current_status,
                        "campaign_id": campaign_id
                    }
                
                return {
                    "message": f"Campaign {campaign_id} has been activated",
                    "previous_status": current_status,
                    "new_status": "active",
                    "campaign_id": campaign_id
                }
            
            return {"error": "Unable to determine campaign status"}
            
        except Exception as e:
            logger.error(f"Unexpected error in activate_campaign: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    def deactivate_campaign(self, campaign_id):
        """Deactivate a campaign by setting status to 'paused'"""
        try:
            logger.debug(f"Attempting to deactivate campaign with ID: {campaign_id}")
            
            # First, get the campaign details to check current status
            campaign = self.get_campaign_by_id(campaign_id)
            
            if "error" in campaign:
                return campaign
            
            if "properties" in campaign:
                current_status = campaign["properties"].get("hs_campaign_status", "unknown")
                
                if current_status == "paused":
                    return {
                        "message": f"Campaign {campaign_id} is already paused",
                        "status": current_status,
                        "campaign_id": campaign_id
                    }
                
                # Try to update status to paused
                update_result = self.update_campaign_status(campaign_id, "paused")
                
                if "error" in update_result:
                    return {
                        "message": f"Could not deactivate campaign {campaign_id}. {update_result['error']}",
                        "status": current_status,
                        "campaign_id": campaign_id
                    }
                
                return {
                    "message": f"Campaign {campaign_id} has been deactivated (paused)",
                    "previous_status": current_status,
                    "new_status": "paused",
                    "campaign_id": campaign_id
                }
            
            return {"error": "Unable to determine campaign status"}
            
        except Exception as e:
            logger.error(f"Unexpected error in deactivate_campaign: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    def create_campaign(self, campaign_data):
        """Create a new campaign in HubSpot Marketing Hub - Simplified working version"""
        try:
            logger.debug("=== CREATING CAMPAIGN ===")
            logger.debug(f"Input data: {campaign_data}")
            
            endpoint = "marketing/v3/campaigns"
            
            # Start with minimal required data (we know this works)
            properties = {
                "hs_name": campaign_data.get("name")
            }
            
            # Add status if provided (only if it's a valid status)
            if campaign_data.get("status"):
                status_mapping = {
                    'ACTIVE': 'active',
                    'PLANNED': 'planned', 
                    'INACTIVE': 'planned',  # Map INACTIVE to planned
                    'IN_PROGRESS': 'in_progress',
                    'PAUSED': 'paused',
                    'COMPLETED': 'completed'
                }
                mapped_status = status_mapping.get(campaign_data["status"].upper(), 'planned')
                properties["hs_campaign_status"] = mapped_status
                logger.debug(f"Status: {campaign_data['status']} -> {mapped_status}")
            
            # Try adding other fields one by one (only safe ones)
            if campaign_data.get("goal"):
                properties["hs_goal"] = campaign_data["goal"]
                
            if campaign_data.get("audience"):
                properties["hs_audience"] = campaign_data["audience"]
                
            if campaign_data.get("notes"):
                properties["hs_notes"] = campaign_data["notes"]
            
            # Handle dates carefully
            if campaign_data.get("start_date"):
                # Keep as string if it's in YYYY-MM-DD format
                start_date = campaign_data["start_date"]
                if len(start_date) == 10 and start_date.count('-') == 2:
                    properties["hs_start_date"] = start_date
                    logger.debug(f"Start date: {start_date}")
            
            if campaign_data.get("end_date"):
                end_date = campaign_data["end_date"]
                if len(end_date) == 10 and end_date.count('-') == 2:
                    properties["hs_end_date"] = end_date
                    logger.debug(f"End date: {end_date}")
            
            data = {"properties": properties}
            logger.debug(f"Final payload: {data}")
            
            response = self._make_request("POST", endpoint, data=data)
            logger.debug(f"HubSpot response: {response}")
            
            if "error" in response:
                logger.error(f"Creation failed: {response['error']}")
            else:
                logger.info(f"Campaign created successfully: {response.get('id', 'Unknown ID')}")
                
            return response
            
        except Exception as e:
            logger.error(f"Exception in create_campaign: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": f"Unexpected error: {str(e)}"}

    def debug_campaign_api(self):
        """Debug campaign API access"""
        try:
            logger.debug("=== DEBUGGING CAMPAIGN API ACCESS ===")
            
            # Test 1: Basic endpoint access
            endpoint = "marketing/v3/campaigns"
            response = self._make_request("GET", f"{endpoint}?limit=1")
            logger.debug(f"Basic campaign endpoint test: {response}")
            
            # Test 2: Check what properties are actually available
            if "results" in response and len(response["results"]) > 0:
                sample_campaign = response["results"][0]
                logger.debug(f"Sample campaign structure: {sample_campaign}")
                if "properties" in sample_campaign:
                    available_props = list(sample_campaign["properties"].keys())
                    logger.debug(f"Available properties: {available_props}")
            
            # Test 3: Try creating with minimal data
            test_data = {
                "properties": {
                    "hs_name": "Test Campaign Debug"
                }
            }
            create_response = self._make_request("POST", endpoint, data=test_data)
            logger.debug(f"Minimal creation test: {create_response}")
            
            return {
                "endpoint_access": response,
                "creation_test": create_response
            }
            
        except Exception as e:
            logger.error(f"Debug error: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"error": str(e)}

    def update_task(self, task_id, task_data):
        """Update an existing task"""
        try:
            logger.debug(f"=== UPDATING TASK {task_id} ===")
            logger.debug(f"Update data: {task_data}")
            
            endpoint = f"crm/v3/objects/tasks/{task_id}"
            properties = {}
            
            # Map fields to HubSpot properties
            if "subject" in task_data:
                properties["hs_task_subject"] = task_data["subject"]
            if "body" in task_data:
                properties["hs_task_body"] = task_data["body"]
            if "status" in task_data:
                status_mapping = {
                    "NOT_STARTED": "NOT_STARTED",
                    "IN_PROGRESS": "IN_PROGRESS",
                    "COMPLETED": "COMPLETED"
                }
                properties["hs_task_status"] = status_mapping.get(task_data["status"].upper(), task_data["status"])
            if "priority" in task_data:
                priority_mapping = {
                    "HIGH": "HIGH",
                    "MEDIUM": "MEDIUM",
                    "LOW": "LOW"
                }
                properties["hs_task_priority"] = priority_mapping.get(task_data["priority"].upper(), task_data["priority"])
            
            data = {"properties": properties}
            logger.debug(f"Update payload: {data}")
            
            response = self._make_request("PATCH", endpoint, data=data)
            
            if "error" in response:
                logger.error(f"Task update failed: {response['error']}")
            else:
                logger.info(f"Task {task_id} updated successfully")
                
            return response
            
        except Exception as e:
            logger.error(f"Exception in update_task: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    def delete_task(self, task_id):
        """Delete a task"""
        try:
            logger.debug(f"=== DELETING TASK {task_id} ===")
            endpoint = f"crm/v3/objects/tasks/{task_id}"
            
            response = self._make_request("DELETE", endpoint)
            
            if "error" in response:
                logger.error(f"Task deletion failed: {response['error']}")
            else:
                logger.info(f"Task {task_id} deleted successfully")
                
            return response
            
        except Exception as e:
            logger.error(f"Exception in delete_task: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}