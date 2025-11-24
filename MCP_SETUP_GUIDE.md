# Figma MCP Server - Setup & Testing Guide

This guide explains how to configure and use the Figma MCP Server with Claude Code.

## 📍 Configuration Location

Claude Code stores MCP server configurations in:
```
/home/nattu/.claude.json
```

The configuration is stored per-project under the `projects` section:
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

## 🚀 Quick Setup

### 1. Add Production MCP Server

Run this command in your terminal:
```bash
claude mcp add --transport http figma https://figma-mcp-server-pkfl.onrender.com/figma/messages
```

### 2. Verify Connection

Check if the server is connected:
```bash
claude mcp list
```

Expected output:
```
Checking MCP server health...

figma: https://figma-mcp-server-pkfl.onrender.com/figma/messages (HTTP) - ✓ Connected
```

### 3. View Server Details

Get detailed information:
```bash
claude mcp get figma
```

## 🔧 Management Commands

### Add MCP Server
```bash
# Production server (Render)
claude mcp add --transport http figma https://figma-mcp-server-pkfl.onrender.com/figma/messages

# Local development server
claude mcp add --transport http figma http://localhost:8003/figma/messages
```

### Remove MCP Server
```bash
claude mcp remove figma -s local
```

### List All MCP Servers
```bash
claude mcp list
```

### View MCP Server Details
```bash
claude mcp get figma
```

## 🧪 Testing the MCP Server

### Method 1: Using Claude Code CLI

Start a new Claude Code session and ask:
```
Use the whoami tool to check my Figma authentication
```

### Method 2: Direct API Testing

Test the initialize endpoint:
```bash
curl -X POST https://figma-mcp-server-pkfl.onrender.com/figma/messages \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {}
  }' | python3 -m json.tool
```

Test the tools/list endpoint:
```bash
curl -X POST https://figma-mcp-server-pkfl.onrender.com/figma/messages \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list"
  }' | python3 -m json.tool
```

Test the whoami tool:
```bash
curl -X POST https://figma-mcp-server-pkfl.onrender.com/figma/messages \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "whoami",
      "arguments": {
        "apiKey": "YOUR_FIGMA_API_TOKEN"
      }
    }
  }' | python3 -m json.tool
```

### Method 3: Check Server Health

```bash
curl https://figma-mcp-server-pkfl.onrender.com/health
```

Expected response:
```json
{
  "status": "healthy",
  "timestamp": "2025-11-24T20:00:00.000000"
}
```

## 🛠️ Available Tools

Your MCP server provides 8 Figma tools:

1. **get_screenshot** - Export designs as images
   - Required: `fileKey`, `nodeId`, `apiKey`

2. **get_design_context** - Generate UI code from designs
   - Required: `fileKey`, `nodeId`, `apiKey`
   - Optional: `clientLanguages`, `clientFrameworks`, `forceCode`

3. **get_metadata** - Get node metadata in XML format
   - Required: `fileKey`, `nodeId`, `apiKey`

4. **get_variable_defs** - Access design variables
   - Required: `fileKey`, `nodeId`, `apiKey`

5. **get_figjam** - Process FigJam boards
   - Required: `fileKey`, `nodeId`, `apiKey`
   - Optional: `includeImagesOfNodes`

6. **get_code_connect_map** - Map components to code
   - Required: `fileKey`, `nodeId`, `apiKey`, `codeConnectLabel`

7. **create_design_system_rules** - Generate design system rules
   - Required: `nodeId`

8. **whoami** - Verify authentication
   - Required: `apiKey`

## 📖 Example Usage with Claude Code

### Get Figma File Information
```
Can you help me fetch the screens available in this Figma design:
https://www.figma.com/design/Ds11FPHQz613dOyylAkzOf/My-Design
```

### Generate Code from Design
```
Generate React code from this Figma component:
https://www.figma.com/file/YOUR_FILE_ID/Design?node-id=123-456
```

### Get Design Screenshots
```
Get a screenshot of the homepage design in this Figma file:
https://www.figma.com/file/YOUR_FILE_ID
```

## 🔑 Environment Variables

The MCP server uses the following environment variables (configured on Render):

- `FIGMA_ACCESS_TOKEN` - Your Figma API access token
- `ANTHROPIC_API_KEY` - Anthropic API key (optional)

To get a Figma API token:
1. Go to https://www.figma.com/developers/api#access-tokens
2. Generate a new personal access token
3. Update the environment variable on Render

## 🐛 Troubleshooting

### Server Shows "Failed to connect"

1. Check if Render deployed the latest code:
   ```bash
   curl https://figma-mcp-server-pkfl.onrender.com/health
   ```

2. Verify JSON-RPC 2.0 support:
   ```bash
   curl -X POST https://figma-mcp-server-pkfl.onrender.com/figma/messages \
     -H "Content-Type: application/json" \
     -d '{"jsonrpc": "2.0", "id": 1, "method": "initialize"}' | grep jsonrpc
   ```

3. Check Render logs for errors

### Rate Limit Errors

Figma API has rate limits (~25-50 requests/min on free tier). The server automatically retries with exponential backoff. Wait 60 seconds between heavy operations.

### Invalid API Key

1. Generate a new token at https://www.figma.com/developers/api#access-tokens
2. Update `FIGMA_ACCESS_TOKEN` in Render dashboard
3. Redeploy the service

## 🔄 Local Development

### Start Local Server
```bash
cd /home/nattu/skillrank/MCP-figma-server
source mcp-venv/bin/activate
uvicorn main:app --reload --port 8003
```

### Configure Claude Code for Local Testing
```bash
claude mcp remove figma -s local
claude mcp add --transport http figma http://localhost:8003/figma/messages
```

### Switch Back to Production
```bash
claude mcp remove figma -s local
claude mcp add --transport http figma https://figma-mcp-server-pkfl.onrender.com/figma/messages
```

## 📊 Server Endpoints

- `GET /` - Server information
- `GET /health` - Health check
- `POST /figma/messages` - MCP protocol endpoint (JSON-RPC 2.0)
- `GET /figma/sse` - Server-Sent Events endpoint
- `POST /save-code` - Save generated code

## 🚦 Current Status

- ✅ Server: Running on Render
- ✅ Protocol: JSON-RPC 2.0 compliant
- ✅ Connection: Verified with Claude Code
- ✅ Tools: 8 Figma tools available
- ✅ Authentication: Working with Figma API

## 📝 Additional Resources

- [MCP Protocol Documentation](https://modelcontextprotocol.io)
- [Figma API Documentation](https://developers.figma.com)
- [Claude Code MCP Guide](https://docs.claude.com/en/docs/claude-code/mcp)

---

**Last Updated:** November 24, 2025
**Server URL:** https://figma-mcp-server-pkfl.onrender.com
**Repository:** https://github.com/GSNadarajan/figma-mcp-server
