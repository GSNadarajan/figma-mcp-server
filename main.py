"""
Figma MCP Server - FastAPI Implementation
Deploy this as a hosted MCP server (Render, Railway, Fly.io, etc.)
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
from datetime import datetime

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
    method: str
    params: Optional[Dict[str, Any]] = None

# ===== MCP Tool Implementations =====
class MCPTools:
    
    @staticmethod
    def get_tool_definitions() -> List[Dict]:
        return [
            {
                "name": "get_screenshot",
                "description": "Generate a screenshot for a given node or the currently selected node in the Figma desktop app",
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
                "name": "get_design_context",
                "description": "Generate UI code for a given node in Figma",
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
                "name": "get_metadata",
                "description": "Get metadata for a node or page in the Figma desktop app in XML format",
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
                "name": "get_variable_defs",
                "description": "Get variable definitions for a given node id",
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
                "name": "get_figjam",
                "description": "Generate UI code for a given FigJam node in Figma",
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
                "name": "get_code_connect_map",
                "description": "Get a mapping of Code Connect information for a node",
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
                "name": "create_design_system_rules",
                "description": "Provides a prompt to generate design system rules for this repo",
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
                "name": "whoami",
                "description": "Returns information about the authenticated user",
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
        
        api_key = arguments.get("apiKey")
        if not api_key:
            return {"error": "API key is required"}
        
        client = FigmaClient(api_key)
        
        try:
            if tool_name == "whoami":
                result = await client.get_user_info()
                return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
            
            file_key = arguments.get("fileKey")
            node_id = arguments.get("nodeId")
            
            if not file_key or not node_id:
                return {"error": "fileKey and nodeId are required"}
            
            if tool_name == "get_screenshot":
                images = await client.get_images(file_key, [node_id])
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(images, indent=2)
                    }]
                }
            
            elif tool_name == "get_design_context":
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
            
            elif tool_name == "get_metadata":
                node_data = await client.get_file_nodes(file_key, [node_id])
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(node_data, indent=2)
                    }]
                }
            
            elif tool_name == "get_variable_defs":
                variables = await client.get_local_variables(file_key)
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(variables, indent=2)
                    }]
                }
            
            elif tool_name == "get_figjam":
                node_data = await client.get_file_nodes(file_key, [node_id])
                return {
                    "content": [{
                        "type": "text",
                        "text": json.dumps(node_data, indent=2)
                    }]
                }
            
            elif tool_name == "get_code_connect_map":
                # Note: Code Connect is not directly available via API
                # This would need to be implemented with custom logic
                return {
                    "content": [{
                        "type": "text",
                        "text": "Code Connect mapping not available via public API"
                    }]
                }
            
            elif tool_name == "create_design_system_rules":
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

# Figma MCP endpoints with /figma prefix
@app.post("/figma/messages")
async def figma_messages_endpoint(request: MCPRequest):
    """Handle Figma MCP protocol messages"""

    if request.method == "tools/list":
        return {
            "tools": MCPTools.get_tool_definitions()
        }

    elif request.method == "tools/call":
        tool_name = request.params.get("name")
        arguments = request.params.get("arguments", {})
        result = await MCPTools.execute_tool(tool_name, arguments)
        return result

    elif request.method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "figma-mcp-server",
                "version": "1.0.0"
            }
        }

    return {"error": "Unknown method"}

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