# Arrotech Hub Integration Credentials Guide

This guide provides step-by-step instructions on how to obtain the necessary OAuth credentials for the third-party integrations in Arrotech Hub.

## Table of Contents
1. [Microsoft Outlook](#1-microsoft-outlook)
2. [Notion](#2-notion)
3. [Trello](#3-trello)
4. [Jira](#4-jira)
5. [Microsoft Teams](#5-microsoft-teams)
6. [Zoom](#6-zoom)
7. [Environment Configuration](#7-environment-configuration)

---

## 1. Microsoft Outlook

To enable Outlook integration (reading/sending emails), you need to register an application in the Microsoft Azure Portal.

1.  **Go to Azure Portal**: Log in to the [Microsoft Azure Portal](https://portal.azure.com/).
2.  **App Registrations**: Navigate to "App registrations" and click **"New registration"**.
3.  **Register App**:
    *   **Name**: `Arrotech Hub` (or your preferred name).
    *   **Supported account types**: "Accounts in any organizational directory (Any Microsoft Entra ID tenant - Multitenant) and personal Microsoft accounts (e.g. Skype, Xbox)". This is required for `common` endpoint usage.
    *   **Redirect URI**: Select **Web** and enter `http://localhost:8000/api/outlook/callback`.
4.  **Client Credentials**:
    *   Find the **Application (client) ID** on the Overview page. Copy this to `OUTLOOK_CLIENT_ID`.
    *   Go to **Certificates & secrets** > **New client secret**. Create one currently and copy the **Value** (not the ID) immediately. This is your `OUTLOOK_CLIENT_SECRET`.
5.  **API Permissions**:
    *   Go to **API Permissions** > **Add a permission** > **Microsoft Graph** > **Delegated permissions**.
    *   Add the following permissions:
        *   `User.Read`
        *   `Mail.Read`
        *   `Mail.ReadWrite`
        *   `Mail.Send`
        *   `offline_access` (crucial for refresh tokens)

## 2. Notion

To enable Notion integration (searching/creating pages), you need to create an integration in the Notion Developer portal.

1.  **Go to My Integrations**: Visit [Notion My Integrations](https://www.notion.so/my-integrations).
2.  **Create New Integration**: Click **"+ New integration"**.
3.  **Configure Integration**:
    *   **Name**: `Arrotech Hub`.
    *   **Associated workspace**: Select the workspace you want to test with.
    *   **Type**: Select **Public**.
        *   *Why?* Arrotech Hub allows external users to connect their own Notion accounts. This requires the OAuth 2.0 flow, which is only available for Public integrations. "Internal" integrations do not support the OAuth flow used by this application.
    *   **Capabilities**: Ensure "Read content", "Update content", and "Insert content" are checked.
4.  **OAuth Credentials** (for Public Integrations/OAuth flow):
    *   If building a public integration for OAuth:
        *   Go to **Distribution** tab.
        *   Toggle "Make integration public" to On.
        *   **Redirect URIs**: Add `http://localhost:8000/api/notion/callback`.
        *   Copy **OAuth client ID** to `NOTION_CLIENT_ID`.
        *   Copy **OAuth client secret** to `NOTION_CLIENT_SECRET`.
    *   *Note: If just using a single workspace internal integration, you typically use an "Internal Integration Secret", but our codebase is set up for OAuth flow.*

## 3. Trello

## 3. Trello

## 3. Trello

Our integration uses the standard **Trello OAuth 1.0a** flow via Trello Power-Ups.

1.  **Go to Power-Ups Admin**: Navigate directly to [https://trello.com/power-ups/admin](https://trello.com/power-ups/admin).
2.  **Create New**: Click the **"New"** or **"Create new Power-Up"** button.
    *   *Troubleshooting*: If you do not see this button:
        *   Verify your Trello account email address.
        *   Visit [https://trello.com/app-key](https://trello.com/app-key) to accept Developer Terms.
3.  **Fill Details**:
    *   **Name**: `Arrotech Hub`.
    *   **Workspace**: Select your development workspace.
    *   **Iframe Connector URL**: You can likely leave this **blank**, or use `http://localhost:3000`.
4.  **API Key & Secret**:
    *   Once created, go to the **API Key** tab.
    *   Use the **API Key** as your `TRELLO_CLIENT_ID`.
    *   Click **"Generate a new Secret"**. Use this as your `TRELLO_CLIENT_SECRET`.
5.  **Allowed Origins**: Add `http://localhost:3000` and `http://localhost:8000`.

## 4. Jira

Jira integration is built on the Atlassian Developer platform using OAuth 2.0 (3LO).

1.  **Go to Developer Console**: Visit [Atlassian Developer Console](https://developer.atlassian.com/console/myapps/).
2.  **Create App**: Click **"Create"** > **"OAuth 2.0 integration"**.
3.  **Name App**: Enter `Arrotech Hub`.
4.  **Permissions (Scopes)**:
    *   Go to **Permissions** in the sidebar.
    *   **Jira API**: Add scopes like `read:jira-work`, `write:jira-work`.
    *   **User Identity API**: You **MUST** add `read:me`. This is required to identify the logged-in user.
    *   **Offline Access**: Ensure `offline_access` is enabled (usually under Jira API or standard scopes).
5.  **Authorization**:
    *   Go to **Authorization** in the sidebar.
    *   **Callback URL**: Add `http://localhost:8000/api/jira/callback`.
6.  **Credentials**:
    *   Go to **Settings** in the sidebar.
    *   Copy **Client ID** to `JIRA_CLIENT_ID`.
    *   Copy **Secret** to `JIRA_CLIENT_SECRET`.

## 5. Microsoft Teams

Similar to Outlook, this uses the Microsoft Graph API.

1.  **Azure Portal**: Use the same app registered for Outlook or create a new one.
2.  **Redirect URI**: Add `http://localhost:8000/api/teams/callback` to the **Web** platform in **Authentication**.
3.  **API Permissions**:
    *   Add these permissions:
        *   `Chat.Read`
        *   `ChannelMessage.Read.All`
        *   `User.Read`
        *   `offline_access`
4.  **Credentials**: Reuse `OUTLOOK_CLIENT_ID`/`SECRET` or use separate `TEAMS_CLIENT_ID`/`SECRET`.

## 6. Zoom

1.  **Zoom Marketplace**: Log in to [Zoom App Marketplace](https://marketplace.zoom.us/).
2.  **Develop**: Select **"Build App"**.
3.  **App Type**: Choose **"OAuth"**.
4.  **Create**:
    *   **App Name**: `Arrotech Hub`.
    *   **App Type**: Account-level or User-managed (User-managed is safer for typical OAuth).
5.  **Credentials**:
    *   Copy **Client ID** to `ZOOM_CLIENT_ID`.
    *   Copy **Client Secret** to `ZOOM_CLIENT_SECRET`.
6.  **Redirect URI**:
    *   In **App Credentials** or **Feature** settings, set Redirect URL to `http://localhost:8000/api/zoom/callback`.
    *   Add `http://localhost:8000` to Command Allow List if using specific features.
7.  **Scopes**: Add `meeting:write`, `meeting:read`, `user:read`.

---

## 7. Environment Configuration

Copy these values into your `.env` file (or rename `.env.example` to `.env` and fill them in).

```bash
# Microsoft Outlook
OUTLOOK_CLIENT_ID=your_client_id
OUTLOOK_CLIENT_SECRET=your_client_secret
OUTLOOK_REDIRECT_URI=http://localhost:8000/api/outlook/callback

# Notion
NOTION_CLIENT_ID=your_client_id
NOTION_CLIENT_SECRET=your_client_secret
NOTION_REDIRECT_URI=http://localhost:8000/api/notion/callback

# Trello
TRELLO_CLIENT_ID=your_api_key
TRELLO_CLIENT_SECRET=your_api_secret
TRELLO_REDIRECT_URI=http://localhost:8000/api/trello/callback

# Jira
JIRA_CLIENT_ID=your_client_id
JIRA_CLIENT_SECRET=your_client_secret
JIRA_REDIRECT_URI=http://localhost:8000/api/jira/callback
```
