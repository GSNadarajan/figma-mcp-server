# Understanding MCP (Model Context Protocol) - Complete Guide

## 🤔 Why Did Claude Use Direct API Instead of Your MCP Server?

### The Problem
You configured an MCP server, but Claude sometimes uses direct Figma API calls instead of your MCP server. Here's why:

### Key Insight: MCP Configuration is PROJECT-SPECIFIC

Your MCP configuration in `/home/nattu/.claude.json` is stored **per-project directory**:

```json
{
  "projects": {
    "/home/nattu/skillrank/MCP-figma-server": {
      "mcpServers": {
        "figma": {
          "type": "http",
          "url": "https://figma-mcp-server-pkfl.onrender.com/figma/messages"
        }
      }
    }
  }
}
```

**This means:**
- ✅ MCP tools are available ONLY when you run Claude Code from `/home/nattu/skillrank/MCP-figma-server`
- ❌ MCP tools are NOT available in other directories
- ❌ MCP tools are NOT available in Claude Code web interface

### Why Claude Used Direct API Yesterday

**Scenario 1: Different Directory**
If you ran Claude Code from a different directory (e.g., `/home/nattu/other-project`), Claude didn't have access to your MCP server.

**Scenario 2: Built-in Figma Tools**
Claude Code has **built-in Figma tools** in its system prompt that directly call Figma API. These tools exist independently of your MCP server:

```
Built-in Tools (Always Available):
- mcp__figma__get_screenshot
- mcp__figma__get_design_context
- mcp__figma__get_metadata
etc.
```

These built-in tools call Figma API directly, NOT your hosted server.

**Scenario 3: Tool Name Confusion**
Your MCP server tools might have different names or Claude chose the built-in tools over your custom MCP tools.

---

## 📖 What is MCP (Model Context Protocol)?

### Simple Explanation
MCP is a **standard protocol** that allows LLMs (like Claude) to:
1. **Discover** what tools/data sources are available
2. **Call** those tools with parameters
3. **Receive** structured responses

Think of it like this:
- **Without MCP:** Claude has to make direct API calls to Figma (hardcoded in its system)
- **With MCP:** Claude can discover and use YOUR custom tools dynamically

### MCP Architecture

```
┌─────────────────┐
│  Claude Code    │  (LLM Client)
│  (Your Chat)    │
└────────┬────────┘
         │ JSON-RPC 2.0
         │ over HTTP/SSE
         ▼
┌─────────────────────┐
│  MCP Server         │  (Your FastAPI Server)
│  (Render/Local)     │
└────────┬────────────┘
         │ REST API
         ▼
┌─────────────────────┐
│  Figma API          │  (External Service)
│  api.figma.com      │
└─────────────────────┘
```

### The Protocol Flow

1. **Initialize:**
   ```json
   Claude → MCP Server
   {
     "jsonrpc": "2.0",
     "id": 1,
     "method": "initialize",
     "params": {"capabilities": {}}
   }

   MCP Server → Claude
   {
     "jsonrpc": "2.0",
     "id": 1,
     "result": {
       "protocolVersion": "2024-11-05",
       "capabilities": {"tools": {}},
       "serverInfo": {"name": "figma-mcp-server"}
     }
   }
   ```

2. **List Tools:**
   ```json
   Claude → MCP Server
   {
     "jsonrpc": "2.0",
     "id": 2,
     "method": "tools/list"
   }

   MCP Server → Claude
   {
     "jsonrpc": "2.0",
     "id": 2,
     "result": {
       "tools": [
         {
           "name": "get_screenshot",
           "description": "...",
           "inputSchema": {...}
         }
       ]
     }
   }
   ```

3. **Call Tool:**
   ```json
   Claude → MCP Server
   {
     "jsonrpc": "2.0",
     "id": 3,
     "method": "tools/call",
     "params": {
       "name": "get_screenshot",
       "arguments": {"fileKey": "...", "nodeId": "..."}
     }
   }

   MCP Server → Claude
   {
     "jsonrpc": "2.0",
     "id": 3,
     "result": {
       "content": [
         {"type": "text", "text": "..."}
       ]
     }
   }
   ```

---

## 🏗️ MCP Protocol Standard (JSON-RPC 2.0)

### Required Request Format
Every request MUST have:
- `jsonrpc`: "2.0" (protocol version)
- `id`: Unique identifier (number or string)
- `method`: The method to call
- `params`: Parameters (optional)

### Required Response Format
Every successful response MUST have:
- `jsonrpc`: "2.0"
- `id`: Same as request
- `result`: The result data

Every error response MUST have:
- `jsonrpc`: "2.0"
- `id`: Same as request (or null)
- `error`: Error object with `code`, `message`, `data`

### Why This Matters
Your original FastAPI server was returning:
```json
{"protocolVersion": "2024-11-05", ...}  ❌ Wrong!
```

After our fix, it returns:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {"protocolVersion": "2024-11-05", ...}  ✅ Correct!
}
```

---

## 🎯 How to Ensure Claude ALWAYS Uses YOUR MCP Server

### Option 1: Make It Global (Recommended)

**For All Projects:**
```bash
# Edit global settings
nano ~/.config/claude/settings.json
```

Add MCP server to global config:
```json
{
  "mcpServers": {
    "figma": {
      "type": "http",
      "url": "https://figma-mcp-server-pkfl.onrender.com/figma/messages"
    }
  }
}
```

**However**, Claude Code currently doesn't fully support global MCP servers in `settings.json`. So use Option 2 instead.

### Option 2: Project-Specific (Current Setup)

Run Claude Code from the correct directory:
```bash
cd /home/nattu/skillrank/MCP-figma-server
claude
```

Or specify the project path:
```bash
claude --project /home/nattu/skillrank/MCP-figma-server
```

### Option 3: Disable Built-in Figma Tools (Advanced)

The issue is Claude has built-in Figma tools that compete with yours. To force it to use ONLY your MCP server:

1. **Check available tools in Claude session:**
   ```
   User: "What Figma tools do you have access to?"
   ```

2. **If you see duplicate tools** (built-in + MCP), you need to:
   - Rename your MCP tools with a unique prefix: `custom_get_screenshot`
   - Or configure permissions to block built-in tools

---

## 🛠️ Best Practices for MCP Server Structure

### Current Structure (Good! ✅)

Your FastAPI server follows good practices:

```python
# ✅ Standard Protocol Compliance
class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[int] = None
    method: str
    params: Optional[Dict[str, Any]] = None

# ✅ Proper Response Format
return {
    "jsonrpc": "2.0",
    "id": request.id,
    "result": result
}

# ✅ Error Handling
return {
    "jsonrpc": "2.0",
    "id": request.id,
    "error": {
        "code": -32603,
        "message": "Internal error",
        "data": str(e)
    }
}
```

### Recommended Improvements

#### 1. **Add Tool Discovery Metadata**
```python
def get_tool_definitions():
    return [
        {
            "name": "get_screenshot",
            "description": "Generate a screenshot for a Figma node",
            "inputSchema": {...},
            # Add these:
            "displayName": "Figma Screenshot",  # Human-readable name
            "tags": ["figma", "screenshot", "design"],  # For filtering
            "examples": [  # Help Claude understand usage
                {
                    "description": "Get homepage screenshot",
                    "arguments": {
                        "fileKey": "ABC123",
                        "nodeId": "1:2"
                    }
                }
            ]
        }
    ]
```

#### 2. **Add Server Capabilities**
```python
elif request.method == "initialize":
    result = {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {},
            "resources": {},  # If you support resources
            "prompts": {},    # If you support prompts
            "logging": {}     # If you support logging
        },
        "serverInfo": {
            "name": "figma-mcp-server",
            "version": "1.0.0"
        },
        "instructions": "Use this server for Figma design to code conversion"
    }
```

#### 3. **Add Logging for Debugging**
```python
import logging

@app.post("/figma/messages")
async def figma_messages_endpoint(request: MCPRequest):
    logging.info(f"MCP Request: method={request.method}, id={request.id}")

    try:
        # ... existing code ...
        logging.info(f"MCP Response: id={request.id}, success=True")
        return response
    except Exception as e:
        logging.error(f"MCP Error: id={request.id}, error={str(e)}")
        return error_response
```

#### 4. **Add Request Validation**
```python
elif request.method == "tools/call":
    tool_name = request.params.get("name")

    # Validate tool exists
    valid_tools = [t["name"] for t in MCPTools.get_tool_definitions()]
    if tool_name not in valid_tools:
        return {
            "jsonrpc": "2.0",
            "id": request.id,
            "error": {
                "code": -32602,
                "message": "Invalid params",
                "data": f"Unknown tool: {tool_name}. Available: {valid_tools}"
            }
        }

    arguments = request.params.get("arguments", {})
    result = await MCPTools.execute_tool(tool_name, arguments)
```

#### 5. **Add Health Check Endpoint**
```python
@app.get("/figma/mcp/health")
async def mcp_health():
    """MCP-specific health check"""
    return {
        "status": "healthy",
        "mcp_version": "2024-11-05",
        "tools_count": len(MCPTools.get_tool_definitions()),
        "figma_api_status": "connected"  # Check Figma API
    }
```

---

## 🧪 How to Verify Claude is Using YOUR MCP Server

### Method 1: Add Logging
Add this to your FastAPI server:
```python
@app.post("/figma/messages")
async def figma_messages_endpoint(request: MCPRequest):
    # Log every request
    print(f"🎯 MCP REQUEST from Claude: {request.method}")

    # ... rest of code ...
```

Then watch the Render logs when you ask Claude to use Figma tools.

### Method 2: Add Unique Response Marker
```python
result = {
    "protocolVersion": "2024-11-05",
    "serverInfo": {
        "name": "figma-mcp-server",
        "version": "1.0.0",
        "marker": "🚀 YOUR_HOSTED_SERVER_ON_RENDER"  # Add this
    }
}
```

Then ask Claude:
```
User: "Initialize the Figma MCP connection and show me the server info"
```

If you see "🚀 YOUR_HOSTED_SERVER_ON_RENDER", it's using your server!

### Method 3: Check Tool Names
Give your tools unique names:
```python
{
    "name": "nattu_figma_get_screenshot",  # Unique prefix
    "description": "..."
}
```

Then when Claude lists tools, you'll see your custom names.

---

## 📊 Comparison: Direct API vs MCP Server

| Aspect | Direct Figma API | Your MCP Server |
|--------|------------------|-----------------|
| **Control** | None - hardcoded in Claude | Full - you control logic |
| **Rate Limiting** | Claude handles | Your server handles (with retry) |
| **Caching** | None | You can add caching |
| **Custom Logic** | No | Yes - add preprocessing |
| **Monitoring** | No visibility | Full logs on Render |
| **Cost Optimization** | No control | You can batch requests |
| **Error Handling** | Generic | Custom error messages |

---

## 🎓 Example: Why Your MCP Server is Better

### Scenario: Generate Code from Figma

**With Direct API (what Claude did yesterday):**
```
User → Claude → Figma API → Response
```
- No retry on rate limits
- No custom processing
- No caching
- You can't see what happened

**With Your MCP Server:**
```
User → Claude → YOUR_SERVER → Figma API → YOUR_SERVER → Claude
                    ↓
              - Retry logic
              - Rate limit handling
              - Custom processing
              - Caching
              - Logging
```

Your server can:
1. **Retry** on rate limits (already implemented!)
2. **Cache** frequently accessed designs
3. **Batch** multiple node requests
4. **Transform** Figma data before sending to Claude
5. **Monitor** usage and errors

---

## ✅ Action Items for You

1. **Always run Claude Code from the correct directory:**
   ```bash
   cd /home/nattu/skillrank/MCP-figma-server
   claude
   ```

2. **Verify MCP server is being used:**
   - Add logging to your FastAPI server
   - Check Render logs when Claude makes requests

3. **Update your MCP server with improvements:**
   - Add the logging from Method 1 above
   - Add unique tool name prefixes
   - Add server marker in responses

4. **Test explicitly:**
   ```
   User: "List all available Figma tools"
   User: "What's the name of the MCP server you're connected to?"
   ```

---

## 🔗 Resources

- [MCP Specification](https://modelcontextprotocol.io/specification)
- [JSON-RPC 2.0 Spec](https://www.jsonrpc.org/specification)
- [Claude Code MCP Docs](https://docs.claude.com/en/docs/claude-code/mcp)
- [Your Server on Render](https://figma-mcp-server-pkfl.onrender.com)

---

**Last Updated:** November 25, 2025
**Your Server:** https://figma-mcp-server-pkfl.onrender.com
**Config File:** /home/nattu/.claude.json
