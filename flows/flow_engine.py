from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
import logging
from Engines.rag_engine.engine import RAGEngine

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
    
    def __init__(self, flow_data: Dict[str, Any], user_input: str, context: List[Any]):
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
        self.context = context
        self.user_input = user_input
        self.current_node = self.get_entry_node()
        self.variables: Dict[str, Any] = {}
        
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


    def handle_aiNode(self, node: Dict[str, Any]) -> NodeResponse:
        """Handle AI response node"""
        try:
            rag_engine = RAGEngine(node, self.context)
            result = rag_engine.run(self.user_input)
            
            # Extract the response content
            response = result.get("response", "")
            
            # Log token usage for credit tracking
            token_usage = result.get("token_usage", {})
            cost_estimate = result.get("cost_estimate", {})
            
            if token_usage and cost_estimate:
                logger.info(f"AI Node Usage - Model: {token_usage.get('model', 'unknown')}, "
                           f"Input tokens: {token_usage.get('input_tokens', 0)}, "
                           f"Output tokens: {token_usage.get('output_tokens', 0)}, "
                           f"Cost: ${cost_estimate.get('total_cost_usd', 0):.6f}")
            
            # Store usage information in variables for potential credit deduction
            variables = {
                "ai_response": response,
                "token_usage": token_usage,
                "cost_estimate": cost_estimate,
                "model": token_usage.get("model", "unknown"),
                "input_tokens": token_usage.get("input_tokens", 0),
                "output_tokens": token_usage.get("output_tokens", 0),
                "total_tokens": token_usage.get("total_tokens", 0),
                "cost_usd": cost_estimate.get("total_cost_usd", 0)
            }

            next_id = self.get_next_node_id(node["id"])
            return NodeResponse(
                responses=[response],
                next_node_id=next_id,
                variables=variables
            )
        
        except Exception as e:
            logger.error(f"Error executing AI node {node['id']}: {e}")
            return NodeResponse(
                responses=[node["data"].get("fallbackResponse", "Sorry, I can't answer that right now.")],
                next_node_id=self.get_next_node_id(node["id"]),
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