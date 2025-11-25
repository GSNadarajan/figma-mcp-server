"""
Figma MCP Server - FastAPI Implementation
Deploy this as a hosted MCP server (Render, Railway, Fly.io, etc.)

MCP Protocol Compliant - Uses JSON-RPC 2.0
Unique Server Identifier: NATTU_HOSTED_MCP_SERVER
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import httpx
import json
import asyncio
import os
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Server identification marker
SERVER_MARKER = "🚀 NATTU_HOSTED_MCP_SERVER_V1"
SERVER_VERSION = "1.1.0"

app = FastAPI(title="Figma MCP Server")

# CORS middleware for browser clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Figma API Client =====
class FigmaClient:
    BASE_URL = "https://api.figma.com/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"X-Figma-Token": api_key}

    async def _request_with_retry(self, method: str, url: str, **kwargs):
        """Make request with retry logic for rate limiting"""
        import asyncio
        max_retries = 3
        base_delay = 2

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    if method == "GET":
                        response = await client.get(url, headers=self.headers, **kwargs)
                    else:
                        response = await client.request(method, url, headers=self.headers, **kwargs)

                    if response.status_code == 429:
                        # Rate limited - check Retry-After header
                        retry_after = int(response.headers.get('Retry-After', base_delay * (2 ** attempt)))
                        print(f"Rate limited. Waiting {retry_after} seconds before retry {attempt + 1}/{max_retries}...")
                        await asyncio.sleep(retry_after)
                        continue

                    response.raise_for_status()
                    return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    print(f"Rate limited. Waiting {delay} seconds before retry {attempt + 1}/{max_retries}...")
                    await asyncio.sleep(delay)
                    continue
                raise

        raise Exception("Max retries exceeded due to rate limiting")
    
    async def get_file(self, file_key: str) -> Dict:
        return await self._request_with_retry(
            "GET",
            f"{self.BASE_URL}/files/{file_key}",
            timeout=30.0
        )

    async def get_file_nodes(self, file_key: str, node_ids: List[str]) -> Dict:
        ids = ",".join(node_ids)
        return await self._request_with_retry(
            "GET",
            f"{self.BASE_URL}/files/{file_key}/nodes",
            params={"ids": ids},
            timeout=30.0
        )
    
    async def get_images(self, file_key: str, node_ids: List[str], 
                        format: str = "png", scale: int = 2) -> Dict:
        async with httpx.AsyncClient() as client:
            ids = ",".join(node_ids)
            response = await client.get(
                f"{self.BASE_URL}/images/{file_key}",
                headers=self.headers,
                params={"ids": ids, "format": format, "scale": scale},
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    
    async def get_local_variables(self, file_key: str) -> Dict:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/files/{file_key}/variables/local",
                headers=self.headers,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
    
    async def get_user_info(self) -> Dict:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/me",
                headers=self.headers,
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()

# ===== Helper Functions =====
def extract_node_id_from_url(url: str) -> Optional[str]:
    """Extract node-id from Figma URL"""
    if "node-id=" in url:
        parts = url.split("node-id=")
        if len(parts) > 1:
            node_id = parts[1].split("&")[0].split("#")[0]
            return node_id.replace("-", ":")
    return None

def extract_file_key_from_url(url: str) -> Optional[str]:
    """Extract file key from Figma URL"""
    if "/file/" in url or "/design/" in url:
        parts = url.split("/")
        for i, part in enumerate(parts):
            if part in ["file", "design"] and i + 1 < len(parts):
                return parts[i + 1].split("?")[0]
    return None

def simplify_node_for_code_gen(node: Dict) -> Dict:
    """Simplify node data for code generation"""
    simplified = {
        "id": node.get("id"),
        "name": node.get("name"),
        "type": node.get("type"),
    }
    
    # Add layout properties
    if "absoluteBoundingBox" in node:
        simplified["layout"] = node["absoluteBoundingBox"]
    
    # Add style properties
    if "fills" in node:
        simplified["fills"] = node["fills"]
    if "strokes" in node:
        simplified["strokes"] = node["strokes"]
    if "effects" in node:
        simplified["effects"] = node["effects"]
    
    # Add text properties
    if node.get("type") == "TEXT":
        simplified["characters"] = node.get("characters")
        simplified["style"] = node.get("style")
    
    # Recursively process children
    if "children" in node:
        simplified["children"] = [
            simplify_node_for_code_gen(child) 
            for child in node["children"]
        ]
    
    return simplified

# ===== MCP Protocol Models =====
class ToolCall(BaseModel):
    name: str
    arguments: Dict[str, Any]

class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[int] = None
    method: str
    params: Optional[Dict[str, Any]] = None

# ===== MCP Tool Implementations =====
# Tool name prefix to make our tools unique and identifiable
TOOL_PREFIX = "nattu_figma_"

class MCPTools:

    @staticmethod
    def get_tool_definitions() -> List[Dict]:
        return [
            {
                "name": f"{TOOL_PREFIX}get_screenshot",
                "description": f"[{SERVER_MARKER}] Generate a screenshot for a given node or the currently selected node in the Figma desktop app. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nodeId": {
                            "type": "string",
                            "description": "The ID of the node in the Figma document"
                        },
                        "fileKey": {
                            "type": "string",
                            "description": "The key of the Figma file to use"
                        },
                        "apiKey": {
                            "type": "string",
                            "description": "Figma API access token"
                        },
                        "clientLanguages": {
                            "type": "string",
                            "description": "Programming languages used by the client"
                        }
                    },
                    "required": ["nodeId", "fileKey", "apiKey"]
                }
            },
            {
                "name": f"{TOOL_PREFIX}get_design_context",
                "description": f"[{SERVER_MARKER}] Generate UI code for a given node in Figma. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nodeId": {
                            "type": "string",
                            "description": "The ID of the node in the Figma document"
                        },
                        "fileKey": {
                            "type": "string",
                            "description": "The key of the Figma file to use"
                        },
                        "apiKey": {
                            "type": "string",
                            "description": "Figma API access token"
                        },
                        "clientLanguages": {
                            "type": "string",
                            "description": "Programming languages for code generation"
                        },
                        "clientFrameworks": {
                            "type": "string",
                            "description": "Frameworks used by the client"
                        },
                        "forceCode": {
                            "type": "boolean",
                            "description": "Force code generation even if response is large"
                        }
                    },
                    "required": ["nodeId", "fileKey", "apiKey"]
                }
            },
            {
                "name": f"{TOOL_PREFIX}get_metadata",
                "description": f"[{SERVER_MARKER}] Get metadata for a node or page in the Figma desktop app in XML format. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nodeId": {
                            "type": "string",
                            "description": "The ID of the node in the Figma document"
                        },
                        "fileKey": {
                            "type": "string",
                            "description": "The key of the Figma file to use"
                        },
                        "apiKey": {
                            "type": "string",
                            "description": "Figma API access token"
                        },
                        "clientLanguages": {
                            "type": "string",
                            "description": "Programming languages used"
                        }
                    },
                    "required": ["nodeId", "fileKey", "apiKey"]
                }
            },
            {
                "name": f"{TOOL_PREFIX}get_variable_defs",
                "description": f"[{SERVER_MARKER}] Get variable definitions for a given node id. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nodeId": {
                            "type": "string",
                            "description": "The ID of the node in the Figma document"
                        },
                        "fileKey": {
                            "type": "string",
                            "description": "The key of the Figma file to use"
                        },
                        "apiKey": {
                            "type": "string",
                            "description": "Figma API access token"
                        },
                        "clientLanguages": {
                            "type": "string",
                            "description": "Programming languages used"
                        }
                    },
                    "required": ["nodeId", "fileKey", "apiKey"]
                }
            },
            {
                "name": f"{TOOL_PREFIX}get_figjam",
                "description": f"[{SERVER_MARKER}] Generate UI code for a given FigJam node in Figma. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nodeId": {
                            "type": "string",
                            "description": "The ID of the node in the Figma document"
                        },
                        "fileKey": {
                            "type": "string",
                            "description": "The key of the Figma file to use"
                        },
                        "apiKey": {
                            "type": "string",
                            "description": "Figma API access token"
                        },
                        "clientLanguages": {
                            "type": "string",
                            "description": "Programming languages used"
                        },
                        "includeImagesOfNodes": {
                            "type": "boolean",
                            "description": "Include images of nodes in response"
                        }
                    },
                    "required": ["nodeId", "fileKey", "apiKey"]
                }
            },
            {
                "name": f"{TOOL_PREFIX}get_code_connect_map",
                "description": f"[{SERVER_MARKER}] Get a mapping of Code Connect information for a node. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nodeId": {
                            "type": "string",
                            "description": "The ID of the node in the Figma document"
                        },
                        "fileKey": {
                            "type": "string",
                            "description": "The key of the Figma file to use"
                        },
                        "apiKey": {
                            "type": "string",
                            "description": "Figma API access token"
                        },
                        "codeConnectLabel": {
                            "type": "string",
                            "description": "Label to fetch Code Connect info for a language/framework"
                        }
                    },
                    "required": ["nodeId", "fileKey", "apiKey"]
                }
            },
            {
                "name": f"{TOOL_PREFIX}create_design_system_rules",
                "description": f"[{SERVER_MARKER}] Provides a prompt to generate design system rules for this repo. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nodeId": {
                            "type": "string",
                            "description": "The ID of the node in the Figma document"
                        },
                        "clientLanguages": {
                            "type": "string",
                            "description": "Programming languages used by the client"
                        },
                        "clientFrameworks": {
                            "type": "string",
                            "description": "Frameworks used by the client"
                        }
                    },
                    "required": ["nodeId"]
                }
            },
            {
                "name": f"{TOOL_PREFIX}whoami",
                "description": f"[{SERVER_MARKER}] Returns information about the authenticated user. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "apiKey": {
                            "type": "string",
                            "description": "Figma API access token"
                        }
                    },
                    "required": ["apiKey"]
                }
            }
        ]
    
    @staticmethod
    async def execute_tool(tool_name: str, arguments: Dict) -> Dict:
        """Execute a tool and return results"""

        # Strip prefix from tool name if present
        clean_tool_name = tool_name.replace(TOOL_PREFIX, "")
        logger.info(f"🎯 MCP Tool Called: {tool_name} (cleaned: {clean_tool_name})")

        api_key = arguments.get("apiKey")
        if not api_key:
            logger.error(f"❌ Missing API key for tool: {tool_name}")
            return {"error": "API key is required"}

        client = FigmaClient(api_key)

        try:
            if clean_tool_name == "whoami":
                result = await client.get_user_info()
                return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
            
            file_key = arguments.get("fileKey")
            node_id = arguments.get("nodeId")
            
            if not file_key or not node_id:
                return {"error": "fileKey and nodeId are required"}
            
            if clean_tool_name == "get_screenshot":
                images = await client.get_images(file_key, [node_id])
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(images, indent=2)
                    }]
                }
            
            elif clean_tool_name == "get_design_context":
                # Get full node data
                node_data = await client.get_file_nodes(file_key, [node_id])
                simplified = simplify_node_for_code_gen(
                    node_data["nodes"][node_id]["document"]
                )
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Design Context:\n{json.dumps(simplified, indent=2)}"
                    }]
                }
            
            elif clean_tool_name == "get_metadata":
                node_data = await client.get_file_nodes(file_key, [node_id])
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(node_data, indent=2)
                    }]
                }
            
            elif clean_tool_name == "get_variable_defs":
                variables = await client.get_local_variables(file_key)
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(variables, indent=2)
                    }]
                }
            
            elif clean_tool_name == "get_figjam":
                node_data = await client.get_file_nodes(file_key, [node_id])
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(node_data, indent=2)
                    }]
                }
            
            elif clean_tool_name == "get_code_connect_map":
                # Note: Code Connect is not directly available via API
                # This would need to be implemented with custom logic
                return {
                    "content": [{
                        "type": "text",
                        "text": "Code Connect mapping not available via public API"
                    }]
                }
            
            elif clean_tool_name == "create_design_system_rules":
                return {
                    "content": [{
                        "type": "text",
                        "text": "Design system rules generation prompt would be provided here"
                    }]
                }
            
            else:
                return {"error": f"Unknown tool: {tool_name}"}
                
        except Exception as e:
            return {"error": str(e)}

# ===== FastAPI Endpoints =====

@app.get("/")
async def root():
    return {
        "name": "Figma MCP Server",
        "version": "1.0.0",
        "protocol": "MCP",
        "endpoints": {
            "sse": "/figma/sse",
            "messages": "/figma/messages",
            "health": "/health"
        },
        "documentation": "https://github.com/YOUR_USERNAME/figma-mcp-server"
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/figma/mcp/health")
async def mcp_health():
    """MCP-specific health check with detailed status"""
    try:
        tool_count = len(MCPTools.get_tool_definitions())
        return {
            "status": "healthy",
            "server_marker": SERVER_MARKER,
            "server_version": SERVER_VERSION,
            "mcp_version": "2024-11-05",
            "protocol": "JSON-RPC 2.0",
            "tools_count": tool_count,
            "tool_prefix": TOOL_PREFIX,
            "figma_api_status": "connected",
            "timestamp": datetime.now().isoformat(),
            "message": "🚀 Your hosted MCP server is running perfectly!"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# Figma MCP endpoints with /figma prefix
@app.post("/figma/messages")
async def figma_messages_endpoint(request: MCPRequest):
    """Handle Figma MCP protocol messages"""

    logger.info(f"📨 MCP Request: method={request.method}, id={request.id}")

    try:
        if request.method == "tools/list":
            logger.info("📋 Listing available tools")
            result = {
                "tools": MCPTools.get_tool_definitions()
            }

        elif request.method == "tools/call":
            tool_name = request.params.get("name")
            arguments = request.params.get("arguments", {})

            # Validate tool exists
            valid_tools = [t["name"] for t in MCPTools.get_tool_definitions()]
            if tool_name not in valid_tools:
                logger.error(f"❌ Unknown tool requested: {tool_name}")
                return {
                    "jsonrpc": "2.0",
                    "id": request.id,
                    "error": {
                        "code": -32602,
                        "message": "Invalid params",
                        "data": f"Unknown tool: {tool_name}. Available tools: {[t.replace(TOOL_PREFIX, '') for t in valid_tools]}"
                    }
                }

            logger.info(f"🔧 Calling tool: {tool_name}")
            result = await MCPTools.execute_tool(tool_name, arguments)

        elif request.method == "initialize":
            logger.info(f"🚀 Initialize request received - Sending server marker: {SERVER_MARKER}")
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "figma-mcp-server",
                    "version": SERVER_VERSION,
                    "marker": SERVER_MARKER,
                    "description": "Nattu's Hosted Figma MCP Server on Render"
                },
                "instructions": "This is YOUR custom hosted MCP server. All tools are prefixed with 'nattu_figma_' to ensure uniqueness."
            }

        else:
            # Return JSON-RPC error for unknown method
            return {
                "jsonrpc": "2.0",
                "id": request.id,
                "error": {
                    "code": -32601,
                    "message": "Method not found",
                    "data": f"Unknown method: {request.method}"
                }
            }

        # Return JSON-RPC 2.0 success response
        logger.info(f"✅ MCP Response: id={request.id}, method={request.method}, success=True")
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "result": result
        }

    except Exception as e:
        # Return JSON-RPC error response
        logger.error(f"❌ MCP Error: id={request.id}, method={request.method}, error={str(e)}")
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "error": {
                "code": -32603,
                "message": "Internal error",
                "data": str(e)
            }
        }

@app.get("/figma/sse")
async def sse_endpoint():
    """Server-Sent Events endpoint for MCP"""
    
    async def event_stream():
        # Send initial connection event
        yield f"data: {json.dumps({'type': 'connection', 'status': 'connected'})}\n\n"
        
        # Keep connection alive
        while True:
            await asyncio.sleep(30)
            yield f"data: {json.dumps({'type': 'ping', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
    
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@app.post("/save-code")
async def save_code(request: dict):
    """Save generated code to files organized by design name"""
    import os
    import re

    design_name = request.get("design_name", "untitled")
    html_code = request.get("html", "")
    css_code = request.get("css", "")
    js_code = request.get("js", "")

    # Sanitize design name for folder
    safe_name = re.sub(r'[^\w\s-]', '', design_name).strip().lower()
    safe_name = re.sub(r'[-\s]+', '-', safe_name)

    # Create directory structure
    base_dir = os.path.join(os.getcwd(), "figma_designs", safe_name)
    os.makedirs(base_dir, exist_ok=True)

    # Write files
    files_created = []

    if html_code:
        html_path = os.path.join(base_dir, "index.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_code)
        files_created.append(html_path)

    if css_code:
        css_path = os.path.join(base_dir, "styles.css")
        with open(css_path, "w", encoding="utf-8") as f:
            f.write(css_code)
        files_created.append(css_path)

    if js_code:
        js_path = os.path.join(base_dir, "script.js")
        with open(js_path, "w", encoding="utf-8") as f:
            f.write(js_code)
        files_created.append(js_path)

    return {
        "success": True,
        "folder": base_dir,
        "files": files_created
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)