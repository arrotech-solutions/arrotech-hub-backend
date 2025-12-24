# Mini-Hub MCP Server

A comprehensive MCP (Model Context Protocol) server that connects AI models to marketing tools and business platforms. Built with FastAPI, featuring multi-platform integrations and AI-powered automation.

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template)

## 🚀 Quick Deploy to Railway


1. **Fork this repo** to your GitHub account
2. **Go to [Railway.app](https://railway.app)** and create a new project
3. **Deploy from GitHub** - select your forked repo
4. **Add PostgreSQL** - Click "+ New" → "Database" → "PostgreSQL"
5. **Set environment variables** (see below)
6. **Done!** Railway auto-deploys on every push

## ⚙️ Environment Variables

Set these in Railway's **Variables** tab:

```env
# Required
ENVIRONMENT=production
SECRET_KEY=your-super-secret-key-at-least-32-chars

# LLM Provider (choose one)
DEFAULT_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-your-openai-api-key
OPENAI_MODEL=gpt-4o

# Optional - Add based on integrations you use
SLACK_BOT_TOKEN=xoxb-your-slack-token
HUBSPOT_API_KEY=your-hubspot-key
STRIPE_SECRET_KEY=sk_live_your-stripe-key
```

## 🔗 Supported Integrations

| Platform | Status | Description |
|----------|--------|-------------|
| **OpenAI** | ✅ | GPT-4o, GPT-4 Turbo, GPT-3.5 |
| **Anthropic** | ✅ | Claude 3 Sonnet |
| **Ollama** | ✅ | Local LLM support |
| **Slack** | ✅ | Team messaging & channels |
| **HubSpot** | ✅ | CRM & marketing automation |
| **Google Analytics 4** | ✅ | Web analytics |
| **WhatsApp** | ✅ | Business messaging |
| **Asana** | ✅ | Project management |
| **Power BI** | ✅ | Business intelligence |
| **Salesforce** | ✅ | Enterprise CRM |
| **Zoom** | ✅ | Video meetings |
| **Microsoft Teams** | ✅ | Team collaboration |
| **Stripe** | ✅ | Payments |
| **M-Pesa** | ✅ | Mobile payments (Kenya) |

## 🛠️ Local Development

```bash
# Clone the repo
git clone https://github.com/your-username/Mini-Hub.git
cd Mini-Hub

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment file
cp env.example .env
# Edit .env with your settings

# Run with Docker (recommended)
docker-compose up -d

# Or run directly
python -m src.main
```

**Access Points:**
- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

## 📊 API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Server info |
| `GET /health` | Health check |
| `POST /auth/register` | User registration |
| `POST /auth/login` | User login |
| `GET /chat/providers` | List LLM providers |
| `POST /chat/conversations` | Create conversation |
| `POST /chat/conversations/{id}/messages` | Send message |
| `GET /connections` | List user connections |
| `POST /connections` | Add new connection |

## 🏗️ Tech Stack

- **Backend**: FastAPI (Python 3.11+)
- **Database**: PostgreSQL + SQLAlchemy
- **Cache**: Redis
- **AI**: OpenAI, Anthropic, Ollama, Gemini
- **Deployment**: Railway, Docker

## 📁 Project Structure

```
Mini-Hub/
├── src/
│   ├── main.py           # Application entry point
│   ├── config.py         # Configuration settings
│   ├── database.py       # Database connection
│   ├── models.py         # SQLAlchemy models
│   ├── routers/          # API route handlers
│   └── services/         # Business logic
├── alembic/              # Database migrations
├── Dockerfile            # Docker build config
├── docker-compose.yml    # Local development
├── railway.json          # Railway deployment config
├── requirements.txt      # Python dependencies
└── env.example           # Environment template
```

## 🔒 Security

- JWT-based authentication
- Rate limiting per tier
- Environment-based secrets
- CORS protection
- Input validation

## 💰 Pricing Tiers

| Tier | Requests/Day | Price |
|------|--------------|-------|
| Free | 100 | $0/month |
| Pro | 10,000 | $49/month |
| Agency | 50,000 | $149/month |
| Enterprise | Custom | Contact us |

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

## 🆘 Support

- **Issues**: [GitHub Issues](https://github.com/your-username/Mini-Hub/issues)
- **Docs**: http://your-app.railway.app/docs
