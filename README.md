# Mini-Hub MCP Server

A comprehensive MCP (Model Context Protocol) server that connects AI models to marketing tools and business intelligence platforms. Built with FastAPI backend and React TypeScript frontend, featuring advanced automation, analytics, and multi-platform integrations.

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
- **Power BI Integration**: Business intelligence and data analytics
- **WhatsApp Integration**: Business messaging and notifications
- **Teams Integration**: Microsoft Teams communication
- **Zoom Integration**: Video conferencing and meeting management
- **Salesforce Integration**: Enterprise CRM and sales automation
- **Connection Management**: Easy setup and testing of integrations
- **Real-time Sync**: Live data synchronization

### 🤖 **AI-Powered Automation**
- **AI Model Integration**: Connect to various AI models (OpenAI, Gemini, Ollama, Hugging Face, Together AI, Anthropic)
- **Automated Workflows**: Custom automation rules with conditional logic
- **Smart Analytics**: AI-driven insights and recommendations
- **Predictive Marketing**: Machine learning for customer behavior
- **Dynamic Tool Registry**: User-specific tools based on active connections
- **Tool Execution Engine**: Intelligent routing and execution of tool calls

### 🔐 **Security & Performance**
- **JWT Authentication**: Secure user authentication
- **Rate Limiting**: API usage protection with tier-based limits
- **SSL/HTTPS**: Encrypted data transmission
- **Database Security**: PostgreSQL with proper access controls
- **Backup Systems**: Automated daily backups
- **Multi-tenant Support**: Isolated user environments

### 📊 **Business Intelligence**
- **Usage Analytics**: Track API usage and performance
- **Payment Analytics**: Revenue and conversion tracking
- **Integration Metrics**: Monitor tool connections
- **Customer Insights**: User behavior and preferences
- **Power BI Analytics**: Comprehensive business intelligence reporting

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

### 🛠️ **Advanced Features**

- **Workflow Builder**: Visual workflow creation with conditional logic
- **File Management**: PDF generation, QR codes, document processing
- **Web Tools**: Web scraping, tracking link generation, SEO tools
- **Content Creation**: AI-powered content generation and templates
- **Multi-tenant Architecture**: Scalable user isolation
- **Real-time Notifications**: WebSocket-based live updates
- **API Rate Limiting**: Intelligent request throttling
- **Error Handling**: Comprehensive error tracking and recovery

### Frontend Features

- **Modern UI/UX**: React 18 with TypeScript and Tailwind CSS
- **Authentication**: Complete login/register system
- **Dashboard**: Real-time overview of connections and usage
- **Responsive Design**: Mobile-first approach
- **Real-time Updates**: React Query for efficient data fetching
- **Workflow Builder UI**: Visual workflow creation interface

## 🛠️ Tech Stack

- **Backend**: Python FastAPI with async support
- **Frontend**: React 18 with TypeScript
- **MCP Protocol**: Official MCP library with enhanced tool support
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Caching**: Redis for session and data caching
- **Payments**: Stripe and M-Pesa integration
- **Styling**: Tailwind CSS with custom components
- **Deployment**: Railway/Fly.io ready with Docker support
- **AI Models**: OpenAI, Gemini, Ollama, Hugging Face, Together AI, Anthropic

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- Node.js 16+
- PostgreSQL database
- Redis instance
- API keys for integrated platforms

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

#### Power BI Integration
1. **Set Up Power BI App Registration**
   - Go to Azure Portal (portal.azure.com)
   - Navigate to Azure Active Directory → App registrations
   - Create a new app registration
   - Add API permissions for Power BI Service
   - Generate a client secret

2. **Get Your Tenant ID**
   - In Azure Portal, go to Azure Active Directory → Overview
   - Copy your Tenant ID (Directory ID)

3. **Configure Power BI in Mini-Hub**
   - Add a new Power BI connection
   - Enter your Client ID, Client Secret, and Tenant ID
   - Test the connection to verify it works

4. **Power BI Features Available**
   - **Workspace Management**: Create, list, and manage workspaces
   - **Dataset Operations**: Refresh datasets, execute DAX queries, get schema
   - **Report Management**: List reports, generate embed tokens
   - **Dashboard Operations**: List and manage dashboards
   - **Analytics Summary**: Get comprehensive Power BI analytics
   - **User Management**: Manage workspace users and permissions

#### WhatsApp Integration
1. **Set Up WhatsApp Business API**
   - Create a WhatsApp Business account
   - Set up your business profile
   - Get your access token and phone number ID

2. **Configure WhatsApp in Mini-Hub**
   - Add a new WhatsApp connection
   - Enter your access token and phone number ID
   - Test the connection

#### Microsoft Teams Integration
1. **Create a Teams App**
   - Go to Microsoft Teams Developer Portal
   - Create a new app with messaging permissions
   - Get your bot token and webhook URL

2. **Configure Teams in Mini-Hub**
   - Add a new Teams connection
   - Enter your bot token and webhook URL
   - Test the connection

#### Zoom Integration
1. **Set Up Zoom App**
   - Go to Zoom App Marketplace
   - Create a new app with meeting permissions
   - Get your client ID and client secret

2. **Configure Zoom in Mini-Hub**
   - Add a new Zoom connection
   - Enter your client ID and client secret
   - Test the connection

#### Salesforce Integration
1. **Set Up Salesforce Connected App**
   - Go to Salesforce Setup → App Manager
   - Create a new connected app
   - Get your client ID and client secret

2. **Configure Salesforce in Mini-Hub**
   - Add a new Salesforce connection
   - Enter your credentials and instance URL
   - Test the connection

### Step 3: Using AI-Powered Marketing Automation

#### Natural Language Commands
Once your tools are connected, you can use natural language to automate marketing tasks:

**Examples:**
- "Add a new contact to HubSpot with email john@example.com"
- "Get the last 24 hours of traffic from GA4"
- "Send a campaign summary to the #marketing Slack channel"
- "Create a deal note in HubSpot for deal ID 123"
- "Refresh all Power BI datasets in workspace ABC"
- "Execute DAX query on dataset XYZ to get sales data"

#### Available Actions

**HubSpot Actions:**
- Read contacts from your CRM
- Create or update contact information
- Add notes to deals
- Search for specific contacts
- Manage companies and deals

**GA4 Actions:**
- Get traffic data for any time period
- Retrieve conversion reports
- Analyze user behavior
- Export analytics data
- Get real-time data

**Slack Actions:**
- Send messages to channels
- Post automated reports
- Send campaign summaries
- Notify teams of important events
- Create and manage channels
- Get channel members

**Asana Actions:**
- Create and manage projects
- Create and assign tasks
- Add comments to tasks
- Manage team members
- Create portfolios for project organization
- Get workspace information

**Power BI Actions:**
- List and manage workspaces
- Refresh datasets and execute DAX queries
- Generate report embed tokens
- Get comprehensive analytics summaries
- Manage workspace users and permissions
- List reports and dashboards
- Get dataset schema information

**WhatsApp Actions:**
- Send messages to customers
- Send media files
- Get message status
- Manage business profile

**Teams Actions:**
- Send messages to channels
- Post adaptive cards
- Get team information
- Manage channel members

**Zoom Actions:**
- Create and manage meetings
- Get meeting information
- Manage participants
- Get recording data

**Salesforce Actions:**
- Query and update records
- Create leads and opportunities
- Manage accounts and contacts
- Execute SOQL queries

### Step 4: Advanced Workflow Automation

#### Workflow Builder
1. **Create Custom Workflows**
   - Use the visual workflow builder
   - Set up conditional logic and branching
   - Define triggers and actions
   - Schedule automated workflows

2. **Conditional Logic Examples**
   ```
   If: Contact value > $10,000
   Then: Send to high-value campaign
   Else: Send to standard campaign
   ```

3. **Variable Substitution**
   - Use `{{input.field_name}}` for input data
   - Use `{{step_X.field_name}}` for step results
   - Dynamic parameter substitution

#### File Management Tools
- **PDF Generation**: Convert HTML to PDF
- **QR Code Generation**: Create QR codes for tracking
- **Document Processing**: Handle various file formats
- **Image Generation**: Create images from text descriptions

#### Web Tools
- **Web Scraping**: Extract data from websites
- **Tracking Link Generation**: Create UTM-tagged links
- **SEO Analysis**: Analyze website performance
- **Social Media Monitoring**: Track mentions and engagement

#### Content Creation
- **AI Content Generation**: Create marketing copy
- **Template System**: Use predefined templates
- **Image Generation**: Create visuals for campaigns
- **Multi-language Support**: Generate content in multiple languages

### Step 5: Dashboard and Monitoring

#### View Your Connections
- Dashboard shows all connected tools
- Green indicators mean connections are active
- Click on any connection to test or reconfigure
- Real-time status updates

#### Monitor Usage
- Track your API usage across all tools
- View rate limits and remaining requests
- Monitor performance and response times
- Get usage analytics and insights

#### Manage Your Account
- Update your profile information
- Change your password
- View your subscription tier
- Access billing information
- Manage API keys and tokens

### Step 6: Troubleshooting

#### Common Issues

**Connection Problems:**
- Verify API keys are correct
- Check if services are accessible
- Ensure proper permissions are set
- Test connections individually

**Authentication Issues:**
- Clear browser cache and cookies
- Check if your session has expired
- Verify your account is active
- Check JWT token validity

**Rate Limiting:**
- Monitor your usage in the dashboard
- Upgrade your plan if needed
- Implement proper error handling
- Use retry logic for failed requests

**Workflow Issues:**
- Check conditional logic syntax
- Verify variable references
- Test individual workflow steps
- Review execution logs

#### Getting Help
- Check the logs in your dashboard
- Review API documentation at `/docs`
- Contact support if issues persist
- Join our Discord community

### Step 7: Best Practices

#### Security
- Use strong, unique passwords
- Regularly rotate API keys
- Monitor access logs
- Enable two-factor authentication when available
- Use environment variables for sensitive data

#### Performance
- Test connections before production use
- Monitor response times
- Set up alerts for failures
- Keep integrations updated
- Use caching for frequently accessed data

#### Data Management
- Regularly backup your configurations
- Export important data periodically
- Clean up old connections
- Monitor data usage and costs
- Implement data retention policies

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
ASANA_ACCESS_TOKEN=your_asana_access_token
ASANA_WORKSPACE_ID=your_asana_workspace_id
POWERBI_CLIENT_ID=your_powerbi_client_id
POWERBI_CLIENT_SECRET=your_powerbi_client_secret
POWERBI_TENANT_ID=your_powerbi_tenant_id
WHATSAPP_TOKEN=your_whatsapp_token
WHATSAPP_PHONE_NUMBER_ID=your_whatsapp_phone_number_id
ZOOM_CLIENT_ID=your_zoom_client_id
ZOOM_CLIENT_SECRET=your_zoom_client_secret
ZOOM_ACCOUNT_ID=your_zoom_account_id
SALESFORCE_CLIENT_ID=your_salesforce_client_id
SALESFORCE_CLIENT_SECRET=your_salesforce_client_secret
SALESFORCE_USERNAME=your_salesforce_username
SALESFORCE_PASSWORD=your_salesforce_password
SALESFORCE_SECURITY_TOKEN=your_salesforce_security_token

# AI Model API Keys
OPENAI_API_KEY=your_openai_api_key
GEMINI_API_KEY=your_gemini_api_key
HUGGINGFACE_API_KEY=your_huggingface_api_key
TOGETHER_API_KEY=your_together_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key

# Stripe
STRIPE_SECRET_KEY=your_stripe_secret
STRIPE_WEBHOOK_SECRET=your_webhook_secret

# App Settings
SECRET_KEY=your_secret_key
ENVIRONMENT=production

# Feature Flags
ENABLE_HUBSPOT=true
ENABLE_SLACK=true
ENABLE_GA4=true
ENABLE_ASANA=true
ENABLE_POWERBI=true
ENABLE_WHATSAPP=true
ENABLE_ZOOM=true
ENABLE_SALESFORCE=true
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

### Platform-Specific Endpoints

All platform operations are accessed through the MCP protocol:

- `GET /mcp/tools`: List available tools for the user
- `POST /mcp/call`: Execute tool calls for any platform
- `POST /connections/test`: Test platform connections

## 🚀 Deployment

### Docker Deployment

1. Build the Docker image:
```bash
docker build -t minihub .
```

2. Run with docker-compose:
```bash
docker-compose up -d
```

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
- **Agency tier**: 50,000 requests/day, team features
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

### Platform Connectors

#### HubSpot Connector
```python
# Read contacts
POST /mcp/call
{
  "name": "hubspot_read_contacts",
  "arguments": {"limit": 10}
}

# Add deal note
POST /mcp/call
{
  "name": "hubspot_add_deal_note",
  "arguments": {
    "deal_id": "123",
    "note": "AI-generated follow-up scheduled"
  }
}
```

#### GA4 Connector
```python
# Get last 24h traffic
POST /mcp/call
{
  "name": "ga4_get_traffic",
  "arguments": {"hours": 24}
}
```

#### Slack Connector
```python
# Send campaign report
POST /mcp/call
{
  "name": "slack_send_report",
  "arguments": {
    "channel": "#marketing",
    "report_type": "campaign_summary"
  }
}
```

#### Power BI Connector
```python
# List workspaces
POST /mcp/call
{
  "name": "powerbi_workspace_management",
  "arguments": {
    "operation": "list"
  }
}

# Execute DAX query
POST /mcp/call
{
  "name": "powerbi_dataset_operations",
  "arguments": {
    "operation": "execute_query",
    "workspace_id": "workspace_id",
    "dataset_id": "dataset_id",
    "dax_query": "EVALUATE Sales"
  }
}
```

#### Asana Connector
```python
# Create project
POST /mcp/call
{
  "name": "asana_project_management",
  "arguments": {
    "operation": "create",
    "project_name": "Marketing Campaign",
    "project_description": "Q4 marketing campaign"
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