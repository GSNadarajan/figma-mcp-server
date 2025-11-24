# Figma MCP Server

FastAPI-based MCP server that exposes Figma design tools for Claude Desktop. Convert designs to code, extract variables, get screenshots, and more.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

## Features

- 🎨 7 Figma tools (screenshots, design context, variables, metadata, etc.)
- 🔄 Automatic rate limit handling with retry logic
- 🚀 Ready for Render, Railway, or Fly.io deployment
- 📡 Server-Sent Events (SSE) for Claude Desktop
- 🔧 CORS support for browser clients

## Connect with Claude Desktop

Edit `claude_desktop_config.json`:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "figma": {
      "url": "https://your-app.onrender.com/figma/sse",
      "type": "sse"
    }
  }
}
```

Restart Claude Desktop and test:
```
List available Figma MCP tools
```

## Local Development

```bash
# Setup
python3 -m venv mcp-venv
source mcp-venv/bin/activate
pip install -r requirements.txt

# Configure
echo 'FIGMA_ACCESS_TOKEN=your-token-here' > .env

# Run
uvicorn main:app --reload --port 8002
```

Server: `http://localhost:8002`

## API Routes

```
GET  /                    # Server info
GET  /health              # Health check
POST /figma/messages      # MCP protocol
GET  /figma/sse          # Server-Sent Events
POST /save-code           # Save generated code
```

## Available Tools

1. `get_screenshot` - Export designs as images
2. `get_design_context` - Extract UI context for code generation
3. `get_metadata` - Get node metadata
4. `get_variable_defs` - Access design variables
5. `get_figjam` - Process FigJam boards
6. `get_code_connect_map` - Map components to code
7. `whoami` - Verify authentication

## Usage with Claude

Ask Claude to use your Figma designs:

```
Generate React code from this Figma file:
https://www.figma.com/file/ABC123/My-Design
```

Claude will use the MCP server to fetch design data and generate code.

## Rate Limits

Figma API limits: ~25-50 requests/min (free tier)

The server handles this automatically:
- Detects 429 errors
- Retries with exponential backoff (2s → 4s → 8s)
- Respects `Retry-After` headers

## Deployment Options

### Render (Recommended)
- Free tier: 750 hours/month
- Auto-deploy from Git
- Built-in HTTPS
- Config: `render.yaml` ✅

### Railway
- Usage-based pricing (~$5/month)
- Fast deployments
- Config: `railway.json` ✅

### Fly.io
- Global edge deployment
- Free tier available
- Config: `Dockerfile` ✅

## Tech Stack

- FastAPI - Web framework
- httpx - Async HTTP
- Pydantic - Data validation
- Uvicorn - ASGI server

## Troubleshooting

**429 Rate Limit Errors:**
- Wait 60 seconds between requests
- Server auto-retries with backoff

**Claude Connection Failed:**
- Verify URL ends with `/figma/sse`
- Check server is running
- Restart Claude Desktop

**Invalid API Key:**
- Get new token: https://www.figma.com/developers/api#access-tokens
- Update environment variable
- Redeploy

## Project Structure

```
figma-mcp-server/
├── main.py              # FastAPI MCP server (all-in-one)
├── requirements.txt     # Python dependencies
├── .env                 # Environment variables (not in git)
├── .gitignore          # Git ignore rules
├── Dockerfile          # Docker deployment config
└── render.yaml         # Render deployment config
```

**Why single-file?**
- Simpler deployment (one file to read)
- Easier for LLMs to understand context
- Common pattern for MCP servers
- FastAPI works great in monolithic style for small services

## Links

- [MCP Protocol](https://modelcontextprotocol.io)
- [Figma API](https://developers.figma.com)


---

Built for design-to-code workflows with Nattu 🚀
