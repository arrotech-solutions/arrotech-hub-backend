# Mini-Hub MCP Server

A comprehensive MCP (Model Context Protocol) server that connects AI models to marketing tools like HubSpot, GA4, and Slack. Built with FastAPI backend and React TypeScript frontend.

## 🚀 Features

### 💳 **Payment Integration**
- **M-Pesa Integration**: Native Kenyan mobile money payments
- **Stripe Integration**: International card payments
- **Subscription Management**: Automated billing and renewals
- **Payment Verification**: Secure transaction validation
- **Kenyan Pricing**: Localized pricing in KES

### 🔗 **Marketing Tool Integrations**
- **HubSpot Integration**: Full CRM and marketing automation
- **Google Analytics 4**: Advanced web analytics and reporting
- **Slack Integration**: Team communication and notifications
- **Asana Integration**: Project management and team collaboration
- **Connection Management**: Easy setup and testing of integrations
- **Real-time Sync**: Live data synchronization

### 🤖 **AI-Powered Automation**
- **AI Model Integration**: Connect to various AI models
- **Automated Workflows**: Custom automation rules
- **Smart Analytics**: AI-driven insights and recommendations
- **Predictive Marketing**: Machine learning for customer behavior

### 🔐 **Security & Performance**
- **JWT Authentication**: Secure user authentication
- **Rate Limiting**: API usage protection
- **SSL/HTTPS**: Encrypted data transmission
- **Database Security**: PostgreSQL with proper access controls
- **Backup Systems**: Automated daily backups

### 📊 **Business Intelligence**
- **Usage Analytics**: Track API usage and performance
- **Payment Analytics**: Revenue and conversion tracking
- **Integration Metrics**: Monitor tool connections
- **Customer Insights**: User behavior and preferences

### 🎯 **Kenyan Market Focus**
- **Local Payment Methods**: M-Pesa integration
- **Kenyan Pricing**: Competitive local pricing
- **Local Support**: Kenyan business hours and support
- **Market Optimization**: Tailored for Kenyan businesses

### 💰 **Pricing Tiers (Kenyan Market)**

- **Free**: KES 0/month - 100 requests/day, basic features
- **Pro**: KES 5,000/month - 10,000 requests/day, full features
- **Agency**: KES 15,000/month - 50,000 requests/day, team features
- **Enterprise**: KES 50,000/month - 100,000 requests/day, custom features

### Frontend Features

- **Modern UI/UX**: React 18 with TypeScript and Tailwind CSS
- **Authentication**: Complete login/register system
- **Dashboard**: Real-time overview of connections and usage
- **Responsive Design**: Mobile-first approach
- **Real-time Updates**: React Query for efficient data fetching

## 🛠️ Tech Stack

- **Backend**: Python FastAPI
- **Frontend**: React 18 with TypeScript
- **MCP Protocol**: Official MCP library
- **Database**: PostgreSQL with SQLAlchemy
- **Caching**: Redis
- **Payments**: Stripe
- **Styling**: Tailwind CSS
- **Deployment**: Railway/Fly.io ready

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- Node.js 16+
- PostgreSQL database
- Redis instance
- API keys for HubSpot, GA4, and Slack

## 📖 How to Use Mini-Hub

### Step 1: Account Setup

1. **Register an Account**
   - Visit the registration page at `/register`
   - Fill in your details: name, email, and password
   - Click "Create account" to get started

2. **Login to Your Account**
   - Go to `/login` and enter your credentials
   - You'll be redirected to your dashboard upon successful login

### Step 2: Connect Your Marketing Tools

#### HubSpot Integration
1. **Get Your HubSpot API Key**
   - Log into your HubSpot account
   - Go to Settings → Integrations → API Keys
   - Create a new API key or copy your existing one

2. **Configure HubSpot in Mini-Hub**
   - In your dashboard, go to "Connections"
   - Click "Add Connection" → "HubSpot"
   - Enter your HubSpot API key
   - Test the connection to verify it works

#### Google Analytics 4 (GA4) Integration
1. **Set Up GA4 Access**
   - Go to Google Analytics
   - Navigate to Admin → Property Settings
   - Copy your Property ID
   - Set up a service account and download credentials

2. **Configure GA4 in Mini-Hub**
   - Add a new GA4 connection
   - Upload your service account credentials file
   - Enter your Property ID
   - Test the connection

#### Slack Integration
1. **Create a Slack App**
   - Go to api.slack.com/apps
   - Create a new app for your workspace
   - Add bot token scopes: `chat:write`, `channels:read`
   - Install the app to your workspace

2. **Configure Slack in Mini-Hub**
   - Add a new Slack connection
   - Enter your bot token
   - Test the connection

#### Asana Integration
1. **Get Your Asana Access Token**
   - Log into your Asana account
   - Go to My Settings → Apps → Manage Developer Apps
   - Create a new personal access token
   - Copy the token (you won't be able to see it again)

2. **Get Your Workspace ID**
   - In Asana, go to your workspace
   - The workspace ID is in the URL: `https://app.asana.com/0/[WORKSPACE_ID]/list`
   - Copy the workspace ID

3. **Configure Asana in Mini-Hub**
   - Add a new Asana connection
   - Enter your access token and workspace ID
   - Test the connection to verify it works

### Step 3: Using AI-Powered Marketing Automation

#### Natural Language Commands
Once your tools are connected, you can use natural language to automate marketing tasks:

**Examples:**
- "Add a new contact to HubSpot with email john@example.com"
- "Get the last 24 hours of traffic from GA4"
- "Send a campaign summary to the #marketing Slack channel"
- "Create a deal note in HubSpot for deal ID 123"

#### Available Actions

**HubSpot Actions:**
- Read contacts from your CRM
- Create or update contact information
- Add notes to deals
- Search for specific contacts

**GA4 Actions:**
- Get traffic data for any time period
- Retrieve conversion reports
- Analyze user behavior
- Export analytics data

**Slack Actions:**
- Send messages to channels
- Post automated reports
- Send campaign summaries
- Notify teams of important events

**Asana Actions:**
- Create and manage projects
- Create and assign tasks
- Add comments to tasks
- Manage team members
- Create portfolios for project organization

### Step 4: Dashboard and Monitoring

#### View Your Connections
- Dashboard shows all connected tools
- Green indicators mean connections are active
- Click on any connection to test or reconfigure

#### Monitor Usage
- Track your API usage across all tools
- View rate limits and remaining requests
- Monitor performance and response times

#### Manage Your Account
- Update your profile information
- Change your password
- View your subscription tier
- Access billing information

### Step 5: Advanced Features

#### Custom Workflows
1. **Create Automation Rules**
   - Set up triggers based on specific events
   - Define actions to take automatically
   - Schedule regular reports and updates

2. **Integration Examples**
   ```
   When: New contact added to HubSpot
   Then: Send welcome message to Slack
   And: Add to email campaign list
   ```

#### API Access
For developers, Mini-Hub provides a REST API:
- Base URL: `https://your-instance.com/api/v1`
- Authentication: Bearer token in headers
- Documentation: Available at `/docs` endpoint

### Step 6: Troubleshooting

#### Common Issues

**Connection Problems:**
- Verify API keys are correct
- Check if services are accessible
- Ensure proper permissions are set

**Authentication Issues:**
- Clear browser cache and cookies
- Check if your session has expired
- Verify your account is active

**Rate Limiting:**
- Monitor your usage in the dashboard
- Upgrade your plan if needed
- Implement proper error handling

#### Getting Help
- Check the logs in your dashboard
- Review API documentation
- Contact support if issues persist

### Step 7: Best Practices

#### Security
- Use strong, unique passwords
- Regularly rotate API keys
- Monitor access logs
- Enable two-factor authentication when available

#### Performance
- Test connections before production use
- Monitor response times
- Set up alerts for failures
- Keep integrations updated

#### Data Management
- Regularly backup your configurations
- Export important data periodically
- Clean up old connections
- Monitor data usage and costs

### Backend Setup

1. Clone the repository:
```bash
git clone <your-repo>
cd Mini-Hub
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp env.example .env
# Edit .env with your API keys
```

4. Run database migrations:
```bash
alembic upgrade head
```

5. Start the backend server:
```bash
python -m src.main
```

### Frontend Setup

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Install Node.js dependencies:
```bash
npm install
```

3. Start the development server:
```bash
npm start
```

4. Access the application:
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000
   - API Docs: http://localhost:8000/docs

## 🔧 Configuration

### Environment Variables

```env
# Database
DATABASE_URL=postgresql://user:pass@localhost/minihub

# Redis
REDIS_URL=redis://localhost:6379

# API Keys
HUBSPOT_API_KEY=your_hubspot_key
GA4_PROPERTY_ID=your_ga4_property_id
GA4_CREDENTIALS_FILE=path/to/credentials.json
SLACK_BOT_TOKEN=your_slack_token

# Stripe
STRIPE_SECRET_KEY=your_stripe_secret
STRIPE_WEBHOOK_SECRET=your_webhook_secret

# App Settings
SECRET_KEY=your_secret_key
ENVIRONMENT=production
```

## 📊 API Endpoints

### MCP Endpoints

- `GET /mcp/`: MCP server info
- `POST /mcp/tools`: List available tools
- `POST /mcp/tools/call`: Execute tool calls

### Management Endpoints

- `GET /api/v1/status`: Server status
- `POST /api/v1/subscriptions`: Create subscription
- `GET /api/v1/usage`: Usage statistics

## 🚀 Deployment

### Railway Deployment

1. Connect your GitHub repository to Railway
2. Set environment variables in Railway dashboard
3. Deploy automatically on push

### Fly.io Deployment

1. Install flyctl: `curl -L https://fly.io/install.sh | sh`
2. Login: `fly auth login`
3. Deploy: `fly deploy`

## 💰 Monetization

The server handles rate limiting and billing automatically:

- **Free tier**: 100 requests/day, basic connectors
- **Pro tier**: 10,000 requests/day, all connectors
- **Enterprise**: Custom limits, white-glove setup

## 🔌 Connector Details

### Enhanced Tools

The Mini-Hub now includes comprehensive enhanced tools for file management, web automation, and content creation:

#### File Management Tools
```python
# Generate PDF from HTML
POST /mcp/tools/call
{
  "name": "file_management",
  "arguments": {
    "operation": "generate_pdf",
    "html_content": "<h1>Report</h1><p>Content here</p>"
  }
}

# Generate QR Code
POST /mcp/tools/call
{
  "name": "file_management",
  "arguments": {
    "operation": "generate_qr",
    "qr_data": "https://example.com",
    "qr_size": 10
  }
}
```

#### Web Tools
```python
# Scrape website data
POST /mcp/tools/call
{
  "name": "web_tools",
  "arguments": {
    "operation": "scrape_website",
    "url": "https://example.com",
    "selectors": {
      "title": "h1",
      "content": "p"
    }
  }
}

# Generate tracking link
POST /mcp/tools/call
{
  "name": "web_tools",
  "arguments": {
    "operation": "generate_tracking_link",
    "original_url": "https://example.com",
    "campaign": "summer-sale",
    "source": "email"
  }
}
```

#### Content Creation Tools
```python
# Generate image from text
POST /mcp/tools/call
{
  "name": "content_creation",
  "arguments": {
    "operation": "generate_image",
    "text": "Welcome to Our Platform",
    "style": "modern",
    "size": [800, 600]
  }
}

# Create content from template
POST /mcp/tools/call
{
  "name": "content_creation",
  "arguments": {
    "operation": "create_from_template",
    "template_name": "email_welcome",
    "variables": {
      "company_name": "Acme Corp",
      "first_name": "John"
    }
  }
}
```

### HubSpot Connector

```python
# Read contacts
GET /mcp/tools/call
{
  "name": "hubspot_read_contacts",
  "arguments": {"limit": 10}
}

# Add deal note
POST /mcp/tools/call
{
  "name": "hubspot_add_deal_note",
  "arguments": {
    "deal_id": "123",
    "note": "AI-generated follow-up scheduled"
  }
}
```

### GA4 Connector

```python
# Get last 24h traffic
GET /mcp/tools/call
{
  "name": "ga4_get_traffic",
  "arguments": {"hours": 24}
}
```

### Slack Connector

```python
# Send campaign report
POST /mcp/tools/call
{
  "name": "slack_send_report",
  "arguments": {
    "channel": "#marketing",
    "report_type": "campaign_summary"
  }
}
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details.

## 🆘 Support

- **Documentation**: [docs.minihub.ai](https://docs.minihub.ai)
- **Email**: support@minihub.ai
- **Discord**: [Join our community](https://discord.gg/minihub) 