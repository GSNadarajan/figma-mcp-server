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
SERVER_VERSION = "1.3.0"  # Performance optimizations + improved tool descriptions matching official Figma MCP

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
        max_retries = 2  # Reduced from 3 to 2 to prevent long waits
        base_delay = 2

        # Set default timeout if not provided
        if 'timeout' not in kwargs:
            kwargs['timeout'] = 20.0  # 20 second timeout for API calls

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    if method == "GET":
                        response = await client.get(url, headers=self.headers, **kwargs)
                    else:
                        response = await client.request(method, url, headers=self.headers, **kwargs)

                    if response.status_code == 429:
                        # Rate limited - check Retry-After header
                        retry_after = min(int(response.headers.get('Retry-After', base_delay * (2 ** attempt))), 10)  # Cap at 10 seconds
                        logger.warning(f"⏱️  Rate limited. Waiting {retry_after}s before retry {attempt + 1}/{max_retries}")
                        await asyncio.sleep(retry_after)
                        continue

                    response.raise_for_status()
                    return response.json()
            except httpx.TimeoutException:
                logger.error(f"⏱️  Request timeout for {url}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(base_delay)
                    continue
                raise Exception("Request timeout - the Figma API took too long to respond")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and attempt < max_retries - 1:
                    delay = min(base_delay * (2 ** attempt), 8)  # Cap at 8 seconds
                    logger.warning(f"⏱️  Rate limited. Waiting {delay}s before retry {attempt + 1}/{max_retries}")
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

def rgb_to_hex(color: Dict) -> str:
    """Convert Figma RGBA to hex color"""
    r = int(color.get("r", 0) * 255)
    g = int(color.get("g", 0) * 255)
    b = int(color.get("b", 0) * 255)
    a = color.get("a", 1)

    if a < 1:
        return f"rgba({r}, {g}, {b}, {a:.2f})"
    return f"#{r:02x}{g:02x}{b:02x}"

def extract_styles_for_css(node: Dict) -> Dict:
    """Extract CSS-ready styles from a Figma node"""
    styles = {}

    # Background color
    if node.get("fills") and len(node["fills"]) > 0:
        fill = node["fills"][0]
        if fill.get("type") == "SOLID" and fill.get("visible", True):
            styles["backgroundColor"] = rgb_to_hex(fill["color"])

    # Border
    if node.get("strokes") and len(node["strokes"]) > 0:
        stroke = node["strokes"][0]
        if stroke.get("type") == "SOLID":
            styles["border"] = f"{node.get('strokeWeight', 1)}px solid {rgb_to_hex(stroke['color'])}"

    # Border radius
    if node.get("cornerRadius"):
        styles["borderRadius"] = f"{node['cornerRadius']}px"

    # Opacity
    if node.get("opacity") and node["opacity"] < 1:
        styles["opacity"] = node["opacity"]

    # Text styles
    if node.get("style"):
        text_style = node["style"]
        if text_style.get("fontFamily"):
            styles["fontFamily"] = text_style["fontFamily"]
        if text_style.get("fontSize"):
            styles["fontSize"] = f"{text_style['fontSize']}px"
        if text_style.get("fontWeight"):
            styles["fontWeight"] = text_style["fontWeight"]
        if text_style.get("letterSpacing"):
            styles["letterSpacing"] = f"{text_style['letterSpacing']}px"
        if text_style.get("lineHeightPx"):
            styles["lineHeight"] = f"{text_style['lineHeightPx']}px"
        if text_style.get("textAlignHorizontal"):
            align_map = {"LEFT": "left", "CENTER": "center", "RIGHT": "right", "JUSTIFIED": "justify"}
            styles["textAlign"] = align_map.get(text_style["textAlignHorizontal"], "left")

    return styles

def simplify_node_for_code_gen(node: Dict, include_images: bool = False, max_depth: int = 4, current_depth: int = 0) -> Dict:
    """Simplify node data for code generation with CSS-ready styles

    Args:
        node: Figma node data
        include_images: Whether to include image references
        max_depth: Maximum recursion depth (default 4 levels)
        current_depth: Current recursion depth (internal use)
    """
    node_type = node.get("type", "")

    simplified = {
        "id": node.get("id"),
        "name": node.get("name"),
        "type": node_type,
        "htmlTag": determine_html_tag(node),
    }

    # Add layout properties
    if "absoluteBoundingBox" in node:
        box = node["absoluteBoundingBox"]
        simplified["layout"] = {
            "width": f"{box.get('width', 0)}px",
            "height": f"{box.get('height', 0)}px",
            "x": box.get("x", 0),
            "y": box.get("y", 0)
        }

    # Extract CSS-ready styles
    simplified["styles"] = extract_styles_for_css(node)

    # Add text content
    if node_type == "TEXT":
        simplified["text"] = node.get("characters", "")

    # Add image references
    if include_images and node_type == "RECTANGLE" and node.get("fills"):
        for fill in node["fills"]:
            if fill.get("type") == "IMAGE":
                simplified["imageRef"] = fill.get("imageRef")

    # Layout properties for container elements
    if node.get("layoutMode"):
        layout_map = {"HORIZONTAL": "row", "VERTICAL": "column"}
        simplified["flexDirection"] = layout_map.get(node["layoutMode"], "column")

        if node.get("primaryAxisAlignItems"):
            simplified["justifyContent"] = node["primaryAxisAlignItems"].lower()
        if node.get("counterAxisAlignItems"):
            simplified["alignItems"] = node["counterAxisAlignItems"].lower()
        if node.get("itemSpacing"):
            simplified["gap"] = f"{node['itemSpacing']}px"
        if node.get("paddingLeft") or node.get("paddingTop"):
            simplified["padding"] = {
                "top": node.get("paddingTop", 0),
                "right": node.get("paddingRight", 0),
                "bottom": node.get("paddingBottom", 0),
                "left": node.get("paddingLeft", 0)
            }

    # Recursively process children (with depth limit to prevent timeouts)
    if "children" in node and current_depth < max_depth:
        children = node["children"]
        # Limit number of children to process (max 20 per level)
        if len(children) > 20:
            logger.warning(f"⚠️  Node has {len(children)} children, limiting to first 20 for performance")
            children = children[:20]
            simplified["childrenTruncated"] = True
            simplified["totalChildren"] = len(node["children"])

        simplified["children"] = [
            simplify_node_for_code_gen(child, include_images, max_depth, current_depth + 1)
            for child in children
        ]
    elif "children" in node and current_depth >= max_depth:
        # Reached max depth - just indicate there are children
        simplified["childrenCount"] = len(node["children"])
        simplified["note"] = "Children omitted due to depth limit (prevents timeouts for complex designs)"

    return simplified

def determine_html_tag(node: Dict) -> str:
    """Determine appropriate HTML tag based on Figma node type and name"""
    node_type = node.get("type", "")
    node_name = node.get("name", "").lower()

    if node_type == "TEXT":
        if "heading" in node_name or "title" in node_name:
            return "h1"
        if "subtitle" in node_name:
            return "h2"
        if "button" in node_name:
            return "button"
        return "p"

    if "button" in node_name:
        return "button"
    if "input" in node_name or "field" in node_name:
        return "input"
    if "nav" in node_name or "menu" in node_name:
        return "nav"
    if "header" in node_name:
        return "header"
    if "footer" in node_name:
        return "footer"

    # Container elements
    if node.get("layoutMode"):
        return "div"

    return "div"

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
                "description": f"[{SERVER_MARKER}] Generate a screenshot image for a given Figma node. Use the nodeId parameter to specify a node id. nodeId parameter is REQUIRED. Use the fileKey parameter to specify the file key. fileKey parameter is REQUIRED. If a URL is provided, extract the file key and node id from the URL. For example, if given the URL https://figma.com/design/pqrs/ExampleFile?node-id=1-2 the extracted fileKey would be `pqrs` and the extracted nodeId would be `1:2`. Returns a direct image URL that can be used in HTML img tags or downloaded. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nodeId": {
                            "type": "string",
                            "description": "The ID of the node in the Figma document, eg. \"123:456\" or \"123-456\". This should be a valid node ID in the Figma document."
                        },
                        "fileKey": {
                            "type": "string",
                            "description": "The key of the Figma file to use. If the URL is provided, extract the file key from the URL. The given URL must be in the format https://figma.com/design/:fileKey/:fileName?node-id=:int1-:int2. The extracted fileKey would be `:fileKey`."
                        },
                        "apiKey": {
                            "type": "string",
                            "description": "Figma API access token"
                        },
                        "clientLanguages": {
                            "type": "string",
                            "description": "A comma separated list of programming languages used by the client in the current context in string form, e.g. `javascript`, `html,css,typescript`, etc. If you do not know, please list `unknown`. This is used for logging purposes to understand which languages are being used. If you are unsure, it is better to list `unknown` than to make a guess."
                        }
                    },
                    "required": ["nodeId", "fileKey", "apiKey"]
                }
            },
            {
                "name": f"{TOOL_PREFIX}get_design_context",
                "description": f"[{SERVER_MARKER}] Extract complete design structure and styling information from a Figma node to enable HTML/CSS code generation. Use the nodeId parameter to specify a node id. Use the fileKey parameter to specify the file key. If a URL is provided, extract the node id from the URL, for example, if given the URL https://figma.com/design/:fileKey/:fileName?node-id=1-2, the extracted nodeId would be `1:2` and the fileKey would be `:fileKey`. The response will contain CSS-ready values (hex colors, px dimensions), suggested HTML tags, layout properties (flexbox/grid), typography, spacing, and a structured JSON tree perfect for code generation. Also includes image URLs for visual assets. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nodeId": {
                            "type": "string",
                            "description": "The ID of the node in the Figma document, eg. \"123:456\" or \"123-456\". This should be a valid node ID in the Figma document."
                        },
                        "fileKey": {
                            "type": "string",
                            "description": "The key of the Figma file to use. If the URL is provided, extract the file key from the URL. The given URL must be in the format https://figma.com/design/:fileKey/:fileName?node-id=:int1-:int2. The extracted fileKey would be `:fileKey`."
                        },
                        "apiKey": {
                            "type": "string",
                            "description": "Figma API access token"
                        },
                        "clientLanguages": {
                            "type": "string",
                            "description": "A comma separated list of programming languages used by the client in the current context in string form, e.g. `javascript`, `html,css,typescript`, etc. If you do not know, please list `unknown`. This is used for logging purposes to understand which languages are being used. If you are unsure, it is better to list `unknown` than to make a guess."
                        },
                        "clientFrameworks": {
                            "type": "string",
                            "description": "A comma separated list of frameworks used by the client in the current context, e.g. `react`, `vue`, `django` etc. If you do not know, please list `unknown`. This is used for logging purposes to understand which frameworks are being used. If you are unsure, it is better to list `unknown` than to make a guess"
                        },
                        "forceCode": {
                            "type": "boolean",
                            "description": "Whether the full design context should always be returned, instead of returning just summary if the output size is too large. Only set this when the user directly requests to force the full context."
                        }
                    },
                    "required": ["nodeId", "fileKey", "apiKey"]
                }
            },
            {
                "name": f"{TOOL_PREFIX}get_metadata",
                "description": f"[{SERVER_MARKER}] IMPORTANT: Always prefer to use {TOOL_PREFIX}get_design_context tool instead. Get metadata for a node or page in the Figma desktop app in XML format. Useful only for getting an overview of the structure, it only includes node IDs, layer types, names, positions and sizes. You can call {TOOL_PREFIX}get_design_context on the node IDs contained in this response. Use the nodeId parameter to specify a node id, it can also be the page id (e.g. 0:1). Extract the node id from the URL, for example, if given the URL https://figma.com/design/:fileKey/:fileName?node-id=1-2, the extracted nodeId would be `1:2`. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nodeId": {
                            "type": "string",
                            "description": "The ID of the node in the Figma document, eg. \"123:456\" or \"123-456\". This should be a valid node ID in the Figma document."
                        },
                        "fileKey": {
                            "type": "string",
                            "description": "The key of the Figma file to use. If the URL is provided, extract the file key from the URL. The given URL must be in the format https://figma.com/design/:fileKey/:fileName?node-id=:int1-:int2. The extracted fileKey would be `:fileKey`."
                        },
                        "apiKey": {
                            "type": "string",
                            "description": "Figma API access token"
                        },
                        "clientLanguages": {
                            "type": "string",
                            "description": "A comma separated list of programming languages used by the client in the current context in string form, e.g. `javascript`, `html,css,typescript`, etc. If you do not know, please list `unknown`. This is used for logging purposes to understand which languages are being used. If you are unsure, it is better to list `unknown` than to make a guess."
                        }
                    },
                    "required": ["nodeId", "fileKey", "apiKey"]
                }
            },
            {
                "name": f"{TOOL_PREFIX}get_variable_defs",
                "description": f"[{SERVER_MARKER}] Get design variable definitions (design tokens) for a given node id. E.g. {{'icon/default/secondary': '#949494'}}. Variables are reusable values that can be applied to all kinds of design properties, such as fonts, colors, sizes and spacings. Use the nodeId parameter to specify a node id. Extract the node id from the URL, for example, if given the URL https://figma.com/design/:fileKey/:fileName?node-id=1-2, the extracted nodeId would be `1:2`. Returns variable collections that can be used as CSS custom properties. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nodeId": {
                            "type": "string",
                            "description": "The ID of the node in the Figma document, eg. \"123:456\" or \"123-456\". This should be a valid node ID in the Figma document."
                        },
                        "fileKey": {
                            "type": "string",
                            "description": "The key of the Figma file to use. If the URL is provided, extract the file key from the URL. The given URL must be in the format https://figma.com/design/:fileKey/:fileName?node-id=:int1-:int2. The extracted fileKey would be `:fileKey`."
                        },
                        "apiKey": {
                            "type": "string",
                            "description": "Figma API access token"
                        },
                        "clientLanguages": {
                            "type": "string",
                            "description": "A comma separated list of programming languages used by the client in the current context in string form, e.g. `javascript`, `html,css,typescript`, etc. If you do not know, please list `unknown`. This is used for logging purposes to understand which languages are being used. If you are unsure, it is better to list `unknown` than to make a guess."
                        }
                    },
                    "required": ["nodeId", "fileKey", "apiKey"]
                }
            },
            {
                "name": f"{TOOL_PREFIX}get_figjam",
                "description": f"[{SERVER_MARKER}] Extract content and structure from a FigJam board node. Use the nodeId parameter to specify a node id. Use the fileKey parameter to specify the file key. If a URL is provided, extract the node id from the URL, for example, if given the URL https://figma.com/board/:fileKey/:fileName?node-id=1-2, the extracted nodeId would be `1:2` and the fileKey would be `:fileKey`. IMPORTANT: This tool only works for FigJam files (collaborative whiteboarding), not regular Figma design files. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nodeId": {
                            "type": "string",
                            "description": "The ID of the node in the Figma document, eg. \"123:456\" or \"123-456\". This should be a valid node ID in the Figma document."
                        },
                        "fileKey": {
                            "type": "string",
                            "description": "The key of the Figma file to use. If the URL is provided, extract the file key from the URL. The given URL must be in the format https://figma.com/board/:fileKey/:fileName?node-id=:int1-:int2. The extracted fileKey would be `:fileKey`."
                        },
                        "apiKey": {
                            "type": "string",
                            "description": "Figma API access token"
                        },
                        "clientLanguages": {
                            "type": "string",
                            "description": "A comma separated list of programming languages used by the client in the current context in string form, e.g. `javascript`, `html,css,typescript`, etc. If you do not know, please list `unknown`. This is used for logging purposes to understand which languages are being used. If you are unsure, it is better to list `unknown` than to make a guess."
                        },
                        "includeImagesOfNodes": {
                            "type": "boolean",
                            "description": "Whether to include screenshot images of nodes in the response"
                        }
                    },
                    "required": ["nodeId", "fileKey", "apiKey"]
                }
            },
            {
                "name": f"{TOOL_PREFIX}get_code_connect_map",
                "description": f"[{SERVER_MARKER}] Get a mapping of Code Connect information linking Figma components to codebase locations. Returns {{[nodeId]: {{codeConnectSrc: 'location of component in codebase', codeConnectName: 'name of component in codebase'}}}}. E.g. {{'1:2': {{codeConnectSrc: 'https://github.com/foo/components/Button.tsx', codeConnectName: 'Button'}}}}. Use the nodeId parameter to specify a node id. Use the fileKey parameter to specify the file key. If a URL is provided, extract the node id from the URL, for example, if given the URL https://figma.com/design/:fileKey/:fileName?node-id=1-2, the extracted nodeId would be `1:2` and the fileKey would be `:fileKey`. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "nodeId": {
                            "type": "string",
                            "description": "The ID of the node in the Figma document, eg. \"123:456\" or \"123-456\". This should be a valid node ID in the Figma document."
                        },
                        "fileKey": {
                            "type": "string",
                            "description": "The key of the Figma file to use. If the URL is provided, extract the file key from the URL. The given URL must be in the format https://figma.com/design/:fileKey/:fileName?node-id=:int1-:int2. The extracted fileKey would be `:fileKey`."
                        },
                        "apiKey": {
                            "type": "string",
                            "description": "Figma API access token"
                        },
                        "codeConnectLabel": {
                            "type": "string",
                            "description": "The label used to fetch Code Connect information for a particular language or framework when multiple Code Connect mappings exist."
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
                "description": f"[{SERVER_MARKER}] Returns information about the authenticated Figma user including name, email, and user ID. If you are experiencing permission issues with other tools (403 Forbidden errors), you can use this tool to get information about who is authenticated and validate the right user is logged in and the API key is valid. This uses YOUR hosted MCP server on Render.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "apiKey": {
                            "type": "string",
                            "description": "Figma API access token to validate"
                        }
                    },
                    "required": ["apiKey"]
                }
            }
        ]
    
    @staticmethod
    async def execute_tool(tool_name: str, arguments: Dict) -> Dict:
        """Execute a tool and return results in Claude-friendly format"""

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
                user_info = f"""**Figma Account Information**

👤 Name: {result.get('handle', 'Unknown')}
📧 Email: {result.get('email', 'N/A')}
🆔 ID: {result.get('id', 'N/A')}

✅ Authentication successful! You can now use this API key to access Figma designs."""
                return {"content": [{"type": "text", "text": user_info}]}

            file_key = arguments.get("fileKey")
            node_id = arguments.get("nodeId")

            if not file_key or not node_id:
                return {"error": "fileKey and nodeId are required"}

            if clean_tool_name == "get_screenshot":
                images_response = await client.get_images(file_key, [node_id])

                if "err" in images_response and images_response["err"]:
                    return {"error": f"Figma API error: {images_response['err']}"}

                image_urls = images_response.get("images", {})
                if not image_urls or node_id not in image_urls:
                    return {"error": f"No image found for node {node_id}"}

                image_url = image_urls[node_id]

                result_text = f"""**Screenshot Generated Successfully**

🖼️  Node ID: `{node_id}`
🔗 Image URL: {image_url}

The screenshot is ready. You can use this URL to display or download the image.
Note: Figma image URLs expire after some time, so use them promptly."""

                return {
                    "content": [
                        {"type": "text", "text": result_text},
                        {"type": "text", "text": f"\n\nImage URL for embedding: {image_url}"}
                    ]
                }

            elif clean_tool_name == "get_design_context":
                # Get full node data
                logger.info(f"🔍 Fetching design context for node {node_id} in file {file_key}")
                node_data = await client.get_file_nodes(file_key, [node_id])

                if "err" in node_data and node_data["err"]:
                    return {"error": f"Figma API error: {node_data['err']}"}

                # Also fetch images for this node
                try:
                    images_response = await client.get_images(file_key, [node_id], scale=2)
                    image_url = images_response.get("images", {}).get(node_id)
                except Exception as e:
                    logger.warning(f"⚠️  Could not fetch image: {e}")
                    image_url = None

                document = node_data["nodes"][node_id]["document"]
                simplified = simplify_node_for_code_gen(document, include_images=True)

                # Create a structured, readable response
                result_text = f"""**Design Context Extracted**

📐 Node: {simplified['name']} (Type: {simplified['type']})
🏷️  HTML Tag: <{simplified['htmlTag']}>
📏 Dimensions: {simplified.get('layout', {}).get('width', 'auto')} × {simplified.get('layout', {}).get('height', 'auto')}

**CSS Styles:**
```css
{json.dumps(simplified.get('styles', {}), indent=2)}
```

**Full Structure for Code Generation:**
```json
{json.dumps(simplified, indent=2)}
```
"""

                if image_url:
                    result_text += f"\n**Visual Reference:**\n🖼️  {image_url}\n"

                result_text += f"""

**Instructions for Code Generation:**
1. Use the `htmlTag` field to determine HTML elements
2. Apply the `styles` object directly as CSS
3. Use `layout` for positioning (width, height)
4. For containers with `flexDirection`, use CSS flexbox
5. For TEXT nodes, use the `text` field for content
6. Process `children` array recursively for nested elements

This structure is optimized for HTML/CSS code generation. All colors are in hex format, dimensions include units, and layout properties map directly to CSS."""

                return {"content": [{"type": "text", "text": result_text}]}

            elif clean_tool_name == "get_metadata":
                node_data = await client.get_file_nodes(file_key, [node_id])

                if "err" in node_data and node_data["err"]:
                    return {"error": f"Figma API error: {node_data['err']}"}

                document = node_data["nodes"][node_id]["document"]

                metadata = f"""**Node Metadata**

Name: {document.get('name', 'Unnamed')}
Type: {document.get('type', 'Unknown')}
ID: {document.get('id', 'N/A')}

Raw metadata (for advanced use):
```json
{json.dumps(node_data, indent=2)}
```"""

                return {"content": [{"type": "text", "text": metadata}]}

            elif clean_tool_name == "get_variable_defs":
                variables = await client.get_local_variables(file_key)

                if not variables or "meta" not in variables:
                    return {"content": [{"type": "text", "text": "No design variables found in this file."}]}

                var_collections = variables.get("meta", {}).get("variableCollections", {})
                var_defs = variables.get("meta", {}).get("variables", {})

                result_text = f"""**Design Variables (Tokens)**

Found {len(var_defs)} variables in {len(var_collections)} collections.

**Collections:**
{json.dumps(list(var_collections.keys()), indent=2)}

**Variables:**
```json
{json.dumps(var_defs, indent=2)}
```

These can be used as CSS custom properties or design tokens."""

                return {"content": [{"type": "text", "text": result_text}]}

            elif clean_tool_name == "get_figjam":
                node_data = await client.get_file_nodes(file_key, [node_id])

                result_text = f"""**FigJam Node Data**

```json
{json.dumps(node_data, indent=2)}
```"""

                return {"content": [{"type": "text", "text": result_text}]}

            elif clean_tool_name == "get_code_connect_map":
                return {
                    "content": [{
                        "type": "text",
                        "text": "⚠️  Code Connect mapping is not available via the public Figma API. This feature requires Figma Enterprise."
                    }]
                }

            elif clean_tool_name == "create_design_system_rules":
                prompt_text = f"""**Design System Rules Generation**

Based on the Figma design at node `{node_id}`, you should:

1. Extract color palette from fills and strokes
2. Identify typography patterns (fonts, sizes, weights)
3. Note spacing patterns (padding, gaps)
4. Document component patterns
5. Create reusable CSS variables

Example output structure:
```css
:root {{
  /* Colors */
  --primary-color: #007bff;
  --secondary-color: #6c757d;

  /* Typography */
  --font-family-base: 'Inter', sans-serif;
  --font-size-base: 16px;

  /* Spacing */
  --spacing-unit: 8px;
}}
```

Use the `get_design_context` tool first to extract the actual design data, then generate these rules."""

                return {"content": [{"type": "text", "text": prompt_text}]}

            else:
                return {"error": f"Unknown tool: {tool_name}"}

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                return {
                    "error": "⚠️  Rate limit exceeded. Please wait 60 seconds before trying again. Figma limits API requests to prevent abuse."
                }
            elif e.response.status_code == 403:
                return {
                    "error": "🔒 Access denied. Check that your Figma API key has permission to access this file."
                }
            elif e.response.status_code == 404:
                return {
                    "error": f"❌ Not found. The file key '{arguments.get('fileKey')}' or node ID '{arguments.get('nodeId')}' doesn't exist or you don't have access."
                }
            else:
                return {"error": f"Figma API error {e.response.status_code}: {str(e)}"}
        except Exception as e:
            logger.error(f"❌ Tool execution error: {str(e)}")
            return {"error": f"Internal error: {str(e)}"}

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
            yield f"data: {json.dumps({'type': 'ping', 'timestamp': datetime.now().isoformat()})}\n\n"
    
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