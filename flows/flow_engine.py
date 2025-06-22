from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
import logging
from openai import OpenAI
import json
import PyPDF2
import requests
from io import BytesIO
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

@dataclass
class NodeResponse:
    """Represents a response from a node's execution"""
    responses: List[str]
    next_node_id: Optional[str]
    variables: Dict[str, Any]

class FlowEngine:
    """
    A generic flow engine that executes flows based on node configurations.
    Handles different node types and maintains execution context.
    """
    
    def __init__(self, flow_data: Dict[str, Any], user_input: str, context: Dict[str, Any]):
        """
        Initialize the flow engine.
        
        Args:
            flow_data: The complete flow configuration including nodes and edges
            user_input: The current user input to process
            context: Additional context data (variables, state, etc.)
        """
        self.nodes = {node["id"]: node for node in flow_data.get("nodes", [])}
        self.edges = flow_data.get("edges", [])
        self.files = context.get("files", [])
        self.gdrive_links = context.get("gdrive_links", [])
        self.context = context or {}
        self.user_input = user_input
        self.current_node = self.get_entry_node()
        self.variables: Dict[str, Any] = {}
        
        # Initialize OpenAI client if API key is in context
        self.openai_client = OpenAI()

    def get_entry_node(self) -> Dict[str, Any]:
        """Find the entry node in the flow"""
        for node in self.nodes.values():
            if node["type"] == "inputNode":  # Entry point is an input node
                return node
        raise ValueError("No input node found in the flow.")

    def get_next_node_id(self, current_node_id: str, condition_result: Optional[bool] = None) -> Optional[str]:
        """
        Determine the next node based on edges and condition results.
        
        Args:
            current_node_id: ID of the current node
            condition_result: Result of condition evaluation (if applicable)
        """
        matching_edges = [
            edge for edge in self.edges 
            if edge["source"] == current_node_id
        ]
        
        if not matching_edges:
            return None
            
        if condition_result is not None:
            # For condition nodes, find edge matching the condition result
            for edge in matching_edges:
                if (edge.get("sourceHandle") == "true" and condition_result) or \
                   (edge.get("sourceHandle") == "false" and not condition_result):
                    return edge["target"]
            return None
        
        # For non-condition nodes, take the first edge
        return matching_edges[0]["target"]

    def run(self) -> List[str]:
        """
        Execute the flow starting from the current node.
        Returns list of responses to send back to the user.
        """
        all_responses: List[str] = []
        
        while self.current_node:
            try:
                if self.current_node["type"] == "endNode":
                    break
                
                node_type = self.current_node["type"]
                handler = self.get_handler(node_type)
                
                logger.info(f"Executing node: {self.current_node['id']} of type: {node_type}")
                
                result = handler(self.current_node)
                
                # Update variables
                self.variables.update(result.variables)
                
                # Collect responses
                if result.responses:
                    all_responses.extend(result.responses)
                
                # Stop if no next node
                if not result.next_node_id:
                    break
                    
                # Move to next node
                self.current_node = self.nodes.get(result.next_node_id)
                
            except Exception as e:
                logger.error(f"Error executing node {self.current_node['id']}: {str(e)}")
                raise
        
        return all_responses

    def get_handler(self, node_type: str) -> Callable:
        """Get the appropriate handler function for a node type"""
        handler_name = f"handle_{node_type}"
        if not hasattr(self, handler_name):
            raise ValueError(f"No handler defined for node type: {node_type}")
        return getattr(self, handler_name)

    def handle_inputNode(self, node: Dict[str, Any]) -> NodeResponse:
        """Handle incoming message node"""
        next_id = self.get_next_node_id(node["id"])
        return NodeResponse(
            responses=[],
            next_node_id=next_id,
            variables={"last_input": self.user_input}
        )

    def handle_messageNode(self, node: Dict[str, Any]) -> NodeResponse:
        """Handle send message node"""
        message = node["data"].get("message", "")
        # Process variables in message
        for var_name, var_value in self.variables.items():
            message = message.replace(f"{{{var_name}}}", str(var_value))
            
        next_id = self.get_next_node_id(node["id"])
        return NodeResponse(
            responses=[message],
            next_node_id=next_id,
            variables={}
        )

    def _get_document_context(self) -> str:
        """
        Retrieves and concatenates content from uploaded files and Google Drive links.
        """
        content = []
        
        # From uploaded files
        for file_info in self.files:
            try:
                with default_storage.open(file_info.file.name, 'rb') as f:
                    if file_info.name.lower().endswith('.pdf'):
                        reader = PyPDF2.PdfReader(f)
                        for page in reader.pages:
                            content.append(page.extract_text())
                    else:
                        # Basic text file reading
                        content.append(f.read().decode('utf-8'))
            except Exception as e:
                logger.error(f"Error reading file {file_info.name}: {e}")

        # From Google Drive links
        for link in self.gdrive_links:
            try:
                # Basic handling for public Google Docs/Sheets
                if "docs.google.com/document" in link:
                    export_url = link.replace('/edit', '/export?format=txt')
                    response = requests.get(export_url)
                    response.raise_for_status()
                    content.append(response.text)
                elif "docs.google.com/spreadsheets" in link:
                    export_url = link.replace('/edit', '/export?format=csv')
                    response = requests.get(export_url)
                    response.raise_for_status()
                    content.append(response.text)
            except Exception as e:
                logger.error(f"Error fetching Google Drive link {link}: {e}")

        return "\n\n".join(content)

    def handle_aiNode(self, node: Dict[str, Any]) -> NodeResponse:
        """Handle AI response node"""
        if not self.openai_client:
            raise ValueError("OpenAI API key not provided in context")
            
        system_prompt = node["data"].get("systemPrompt", "")
        model = node["data"].get("model", "gpt-4o")
        fallback_response = node["data"].get("fallbackResponse", "I can't answer that right now.")
        extra_instructions = node["data"].get("extraInstructions", "Mention the 30% discount where relevant")

        # document_context = self._get_document_context()
        document_context = ""
        
        # Combine prompts and context
        final_system_prompt = f"""{system_prompt}
        You have the following context from documents to help you answer:
        ---
        {document_context}
        ---

        {extra_instructions}
        """
        
        # Replace variables in system prompt
        for var_name, var_value in self.variables.items():
            final_system_prompt = final_system_prompt.replace(f"{{{var_name}}}", str(var_value))
        
        try:
            response = self.openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": final_system_prompt},
                    {"role": "user", "content": self.user_input}
                ]
            )
            
            ai_response = response.choices[0].message.content
            
            next_id = self.get_next_node_id(node["id"])
            return NodeResponse(
                responses=[ai_response],
                next_node_id=next_id,
                variables={"ai_response": ai_response}
            )
            
        except Exception as e:
            logger.error(f"Error calling OpenAI API: {str(e)}")
            return NodeResponse(
                responses=[fallback_response],
                next_node_id=self.get_next_node_id(node["id"]), # Still proceed in flow
                variables={}
            )

    def handle_conditionNode(self, node: Dict[str, Any]) -> NodeResponse:
        """Handle condition node"""
        variable = node["data"].get("variable", "")
        condition = node["data"].get("condition", "")
        value = node["data"].get("value", "")
        
        var_value = self.variables.get(variable, self.user_input)
        
        result = False
        if condition == "equals":
            result = str(var_value).lower() == str(value).lower()
        elif condition == "contains":
            result = str(value).lower() in str(var_value).lower()
        elif condition == "startsWith":
            result = str(var_value).lower().startswith(str(value).lower())
        elif condition == "endsWith":
            result = str(var_value).lower().endswith(str(value).lower())
            
        next_id = self.get_next_node_id(node["id"], condition_result=result)
        return NodeResponse(
            responses=[],
            next_node_id=next_id,
            variables={"condition_result": result}
        ) 