using MCPSharp;
using System.Net.Http.Headers;
using System.Text.Json;
using Microsoft.AspNetCore.WebUtilities;
using Autodesk.Authentication;
using Autodesk.Authentication.Model;
using System.Diagnostics;
using System.Net;
using System.Text;
using Microsoft.Extensions.Configuration;
using System;

namespace IssuesMCPServer
{
	public class Program
	{
		private static TokenHandler _tokenHandler;

		// Main entry point.
		public static async Task Main(string[] args)
		{
			try
			{
				LogToDebug("=== MCP Server Starting ===");

				// Initialize configuration
				var config = new APS
				{
					ClientId = Environment.GetEnvironmentVariable("APS_CLIENT_ID"),
					ClientSecret = Environment.GetEnvironmentVariable("APS_CLIENT_SECRET"),
					RedirectUri = Environment.GetEnvironmentVariable("APS_REDIRECT_URI") ?? "http://localhost:3000/api/aps/callback/oauth"
				};

				if (string.IsNullOrEmpty(config.ClientId) || string.IsNullOrEmpty(config.ClientSecret))
				{
					LogToDebug("Error: ClientId or ClientSecret is not configured in appsettings.json");
					Environment.Exit(1);
				}

				LogToDebug("Configuration loaded successfully");

				// Initialize token handler (but don't get token yet)
				_tokenHandler = new TokenHandler(config);
				LogToDebug("Token handler initialized");

				// Register tools
				LogToDebug("Registering MCP tools...");
				MCPServer.Register<AutodeskTools>();
				LogToDebug("Tools registered successfully");

				// Start the MCP server
				LogToDebug("Starting MCP server...");
				await MCPServer.StartAsync("AutodeskAccServer", "1.0.0");

				LogToDebug("MCP server started and should be running indefinitely");
			}
			catch (Exception ex)
			{
				LogToDebug($"FATAL ERROR: {ex.Message}");
				LogToDebug($"Stack trace: {ex.StackTrace}");
				Environment.Exit(1);
			}
		}

		// Helper method to log to stderr
		public static void LogToDebug(string message)
		{
			Console.Error.WriteLine($"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {message}");
			Console.Error.Flush(); // Ensure immediate output
		}

		/// <summary>
		/// A class to hold the tools for interacting with the Autodesk API.
		/// All public methods with the [McpTool] attribute will be exposed.
		/// </summary>
		[McpTool(Description = "Tools for interacting with the Autodesk Construction Cloud (ACC) API to retrieve hubs, projects, and issues.")]
		public class AutodeskTools
		{
			private readonly HttpClient _client;

			public AutodeskTools()
			{
				LogToDebug("AutodeskTools constructor called");
				_client = new HttpClient();
				_client.DefaultRequestHeaders.Accept.Clear();
				_client.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
				LogToDebug("AutodeskTools initialized");
			}

			/// <summary>
			/// Retrieves a list of all hubs associated with the authenticated user.
			/// </summary>
			/// <returns>A JSON string containing the list of hubs.</returns>
			[McpTool(Description = "Retrieves a list of all ACC hubs for the authenticated user.")]
			public async Task<string> GetHubsAsync()
			{
				LogToDebug("GetHubsAsync called");
				var url = "https://developer.api.autodesk.com/project/v1/hubs?filter[extension.type]=hubs:autodesk.bim360:Account";
				return await MakeApiRequest(url);
			}

			/// <summary>
			/// Retrieves a list of projects for a given hub ID.
			/// </summary>
			/// <param name="hubId">The ID of the hub.</param>
			/// <returns>A JSON string containing the list of projects.</returns>
			[McpTool(Description = "Retrieves a list of projects for a specific hub.")]
			public async Task<string> GetProjectsAsync([McpParameter(true, Description = "The unique ID of the hub.")] string hubId)
			{
				LogToDebug($"GetProjectsAsync called with hubId: {hubId}");
				var url = $"https://developer.api.autodesk.com/project/v1/hubs/{hubId}/projects";
				return await MakeApiRequest(url);
			}

			/// <summary>
			/// Retrieves a list of issues for a given project ID, with optional filters.
			/// </summary>
			/// <param name="projectId">The ID of the project.</param>
			/// <param name="issueTypeId">Optional: The ID of the issue type to filter by.</param>
			/// <param name="createdAtStart">Optional: The start date (YYYY-MM-DD) to filter issues created after this date.</param>
			/// <returns>A JSON string containing the list of issues.</returns>
			[McpTool(Description = "Retrieves a list of issues for a project, with optional filters for issue type and creation date.")]
			public async Task<string> GetIssuesAsync(
				[McpParameter(true, Description = "The unique ID of the project.")] string projectId,
				[McpParameter(false, Description = "The ID of the issue type to filter by.")] string? issueTypeId = null,
				[McpParameter(false, Description = "The start date (YYYY-MM-DD) to filter issues created after this date.")] string? createdAtStart = null)
			{
				LogToDebug($"GetIssuesAsync called with projectId: {projectId}");
				var baseUrl = $"https://developer.api.autodesk.com/construction/issues/v1/projects/{projectId}/issues";
				var queryParams = new Dictionary<string, string>();

				if (!string.IsNullOrEmpty(issueTypeId))
				{
					queryParams["filter[issueTypeId]"] = issueTypeId;
				}

				if (!string.IsNullOrEmpty(createdAtStart))
				{
					queryParams["filter[createdAt]"] = $"{createdAtStart}..";
				}

				var finalUrl = queryParams.Count > 0
					? QueryHelpers.AddQueryString(baseUrl, queryParams)
					: baseUrl;
				return await MakeApiRequest(finalUrl);
			}

			[McpTool(Description = "Creates a new issue in a project with comprehensive field support.")]
			public async Task<string> CreateIssueAsync(
		[McpParameter(true, "The unique ID of the project.")] string projectId,
		[McpParameter(true, "The title of the issue.")] string title,
		[McpParameter(true, "The description of the issue.")] string description,
		[McpParameter(false, "The ID of the issue subtype.")] string issueSubtypeId = null,
		[McpParameter(false, "The initial status of the issue.")] string status = "open",
		[McpParameter(false, "The user/role ID to assign the issue to.")] string assignedTo = null,
		[McpParameter(false, "The type of assignee (user or role).")] string assignedToType = null,
		[McpParameter(false, "The due date for the issue (YYYY-MM-DD).")] string dueDate = null,
		[McpParameter(false, "The start date for the issue (YYYY-MM-DD).")] string startDate = null,
		[McpParameter(false, "The location ID for the issue.")] string locationId = null,
		[McpParameter(false, "Location details text.")] string locationDetails = null,
		[McpParameter(false, "The root cause ID for the issue.")] string rootCauseId = null,
		[McpParameter(false, "The issue template ID.")] string issueTemplateId = null,
		[McpParameter(false, "Whether the issue is published.")] bool published = true,
		[McpParameter(false, "List of permitted actions.")] List<string> permittedActions = null,
		[McpParameter(false, "List of watcher user IDs.")] List<string> watchers = null,
		[McpParameter(false, "List of custom attributes.")] List<CustomAttribute> customAttributes = null,
		[McpParameter(false, "GPS latitude coordinate.")] double? latitude = null,
		[McpParameter(false, "GPS longitude coordinate.")] double? longitude = null,
		[McpParameter(false, "Snapshot URN (for image attachments).")] string snapshotUrn = null,
		[McpParameter(false, "Whether snapshot has markups.")] bool snapshotHasMarkups = false)
			{
				try
				{
					LogToDebug($"CreateIssueAsync called with projectId: {projectId}, title: {title}");

					var url = $"https://developer.api.autodesk.com/construction/issues/v1/projects/{projectId}/issues";

					// Build attributes object
					var attributes = new Dictionary<string, object>
			{
				{ "title", title },
				{ "description", description },
				{ "status", status },
				{ "published", published },
				{ "snapshotHasMarkups", snapshotHasMarkups }
			};

					// Add optional fields if provided
					if (!string.IsNullOrEmpty(issueSubtypeId)) attributes["issueSubtypeId"] = issueSubtypeId;
					if (!string.IsNullOrEmpty(assignedTo)) attributes["assignedTo"] = assignedTo;
					if (!string.IsNullOrEmpty(assignedToType)) attributes["assignedToType"] = assignedToType;
					if (!string.IsNullOrEmpty(dueDate)) attributes["dueDate"] = dueDate;
					if (!string.IsNullOrEmpty(startDate)) attributes["startDate"] = startDate;
					if (!string.IsNullOrEmpty(locationId)) attributes["locationId"] = locationId;
					if (!string.IsNullOrEmpty(locationDetails)) attributes["locationDetails"] = locationDetails;
					if (!string.IsNullOrEmpty(rootCauseId)) attributes["rootCauseId"] = rootCauseId;
					if (!string.IsNullOrEmpty(issueTemplateId)) attributes["issueTemplateId"] = issueTemplateId;
					if (!string.IsNullOrEmpty(snapshotUrn)) attributes["snapshotUrn"] = snapshotUrn;

					// Handle collections
					if (permittedActions != null && permittedActions.Any()) attributes["permittedActions"] = permittedActions;
					if (watchers != null && watchers.Any()) attributes["watchers"] = watchers;
					if (customAttributes != null && customAttributes.Any())
						attributes["customAttributes"] = customAttributes.Select(a => new
						{
							attributeDefinitionId = a.AttributeDefinitionId,
							value = a.Value
						});

					// Handle GPS coordinates
					if (latitude != null && longitude != null)
					{
						attributes["gpsCoordinates"] = new
						{
							latitude = latitude,
							longitude = longitude
						};
					}

					// Use flat structure - Autodesk Construction Issues API doesn't use JSON:API format
					var payload = attributes;

					var content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");

					var currentToken = await GetValidToken();
					if (string.IsNullOrEmpty(currentToken))
					{
						LogToDebug("No valid token available");
						return JsonSerializer.Serialize(new { error = "Authentication required - please authenticate first" }, new JsonSerializerOptions { WriteIndented = true });
					}

					_client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", currentToken);

					LogToDebug("Sending POST request to create issue...");
					var response = await _client.PostAsync(url, content);

					LogToDebug($"Create issue response status: {response.StatusCode}");
					
					if (!response.IsSuccessStatusCode)
					{
						// Capture the actual error response body
						var errorContent = await response.Content.ReadAsStringAsync();
						LogToDebug($"Create Issue API Error Response: {errorContent}");
						LogToDebug($"Request URL was: {url}");
						LogToDebug($"Request payload was: {JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true })}");
						
						// Try to format error JSON if possible
						try
						{
							var errorJson = JsonDocument.Parse(errorContent);
							var formattedError = JsonSerializer.Serialize(errorJson, new JsonSerializerOptions { WriteIndented = true });
							LogToDebug($"Formatted Create Issue Error Response: {formattedError}");
							
							// Return the actual API error response instead of generic message
							return JsonSerializer.Serialize(new { 
								error = "Failed to create issue", 
								status_code = (int)response.StatusCode,
								status_description = response.StatusCode.ToString(),
								api_error_response = errorJson,
								request_url = url,
								request_payload = payload
							}, new JsonSerializerOptions { WriteIndented = true });
						}
						catch (JsonException)
						{
							// If error response is not JSON, return as text
							return JsonSerializer.Serialize(new { 
								error = "Failed to create issue", 
								status_code = (int)response.StatusCode,
								status_description = response.StatusCode.ToString(),
								api_error_response = errorContent,
								request_url = url,
								request_payload = payload
							}, new JsonSerializerOptions { WriteIndented = true });
						}
					}

					response.EnsureSuccessStatusCode();

					var result = await response.Content.ReadAsStringAsync();
					LogToDebug("Issue created successfully");
					
					// Format the JSON response for better readability
					try
					{
						var jsonDocument = JsonDocument.Parse(result);
						var formattedJson = JsonSerializer.Serialize(jsonDocument, new JsonSerializerOptions { WriteIndented = true });
						LogToDebug("Create issue JSON response formatted successfully");
						return formattedJson;
					}
					catch (JsonException)
					{
						LogToDebug("Create issue response is not valid JSON, returning as-is");
						return result;
					}
				}
				catch (Exception ex)
				{
					LogToDebug($"Error in CreateIssueAsync: {ex.Message}");
					return JsonSerializer.Serialize(new { error = $"Failed to create issue: {ex.Message}" }, new JsonSerializerOptions { WriteIndented = true });
				}
			}

			/// <summary>
			/// Retrieves a single issue by its ID.
			/// </summary>
			/// <param name="projectId">The ID of the project.</param>
			/// <param name="issueId">The ID of the issue to retrieve.</param>
			/// <returns>A JSON string containing the issue details.</returns>
			[McpTool(Description = "Retrieves a single issue by its ID from a project.")]
			public async Task<string> GetIssueByIdAsync(
				[McpParameter(true, Description = "The unique ID of the project.")] string projectId,
				[McpParameter(true, Description = "The unique ID of the issue to retrieve.")] string issueId)
			{
				LogToDebug($"GetIssueByIdAsync called with projectId: {projectId}, issueId: {issueId}");
				var url = $"https://developer.api.autodesk.com/construction/issues/v1/projects/{projectId}/issues/{issueId}";
				return await MakeApiRequest(url);
			}

			[McpTool(Description = "Updates an issue with various fields including status, title, description, due date, etc.")]
			public async Task<string> UpdateIssueAsync(
				[McpParameter(true, "The unique ID of the project.")] string projectId,
				[McpParameter(true, "The unique ID of the issue.")] string issueId,
				[McpParameter(false, "The new title for the issue.")] string title = null,
				[McpParameter(false, "The new description for the issue.")] string description = null,
				[McpParameter(false, "The new status for the issue.")] string status = null,
				[McpParameter(false, "The user ID to assign the issue to.")] string assignedTo = null,
				[McpParameter(false, "The type of assignee (user or role).")] string assignedToType = null,
				[McpParameter(false, "The due date for the issue (YYYY-MM-DD).")] string dueDate = null,
				[McpParameter(false, "The start date for the issue (YYYY-MM-DD).")] string startDate = null,
				[McpParameter(false, "The location ID for the issue.")] string locationId = null,
				[McpParameter(false, "Location details text.")] string locationDetails = null,
				[McpParameter(false, "Whether the issue is published.")] bool? published = null,
				[McpParameter(false, "GPS latitude coordinate.")] double? latitude = null,
				[McpParameter(false, "GPS longitude coordinate.")] double? longitude = null)
			{
				try
				{
					LogToDebug($"UpdateIssueAsync called with projectId: {projectId}, issueId: {issueId}");

					var url = $"https://developer.api.autodesk.com/construction/issues/v1/projects/{projectId}/issues/{issueId}";

					var attributes = new Dictionary<string, object>();

					// Add only the fields that were provided
					if (title != null) attributes["title"] = title;
					if (description != null) attributes["description"] = description;
					if (status != null) attributes["status"] = status;
					if (assignedTo != null) attributes["assignedTo"] = assignedTo;
					if (assignedToType != null) attributes["assignedToType"] = assignedToType;
					if (dueDate != null) attributes["dueDate"] = dueDate;
					if (startDate != null) attributes["startDate"] = startDate;
					if (locationId != null) attributes["locationId"] = locationId;
					if (locationDetails != null) attributes["locationDetails"] = locationDetails;
					if (published != null) attributes["published"] = published;

					// Handle GPS coordinates if provided
					if (latitude != null && longitude != null)
					{
						attributes["gpsCoordinates"] = new
						{
							latitude = latitude,
							longitude = longitude
						};
					}

					// Use flat structure - Autodesk Construction Issues API doesn't use JSON:API format
					var payload = attributes;

					var content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");

					var currentToken = await GetValidToken();
					if (string.IsNullOrEmpty(currentToken))
					{
						LogToDebug("No valid token available");
						return JsonSerializer.Serialize(new { error = "Authentication required - please authenticate first" }, new JsonSerializerOptions { WriteIndented = true });
					}

					_client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", currentToken);

					LogToDebug("Sending PATCH request to update issue...");
					var request = new HttpRequestMessage(new HttpMethod("PATCH"), url) { Content = content };
					var response = await _client.SendAsync(request);

					LogToDebug($"Update issue response status: {response.StatusCode}");
					
					if (!response.IsSuccessStatusCode)
					{
						// Capture the actual error response body
						var errorContent = await response.Content.ReadAsStringAsync();
						LogToDebug($"Update Issue API Error Response: {errorContent}");
						LogToDebug($"Request URL was: {url}");
						LogToDebug($"Request payload was: {JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true })}");
						
						// Try to format error JSON if possible
						try
						{
							var errorJson = JsonDocument.Parse(errorContent);
							var formattedError = JsonSerializer.Serialize(errorJson, new JsonSerializerOptions { WriteIndented = true });
							LogToDebug($"Formatted Update Issue Error Response: {formattedError}");
							
							// Return the actual API error response instead of generic message
							return JsonSerializer.Serialize(new { 
								error = "Failed to update issue", 
								status_code = (int)response.StatusCode,
								status_description = response.StatusCode.ToString(),
								api_error_response = errorJson,
								request_url = url,
								request_payload = payload
							}, new JsonSerializerOptions { WriteIndented = true });
						}
						catch (JsonException)
						{
							// If error response is not JSON, return as text
							return JsonSerializer.Serialize(new { 
								error = "Failed to update issue", 
								status_code = (int)response.StatusCode,
								status_description = response.StatusCode.ToString(),
								api_error_response = errorContent,
								request_url = url,
								request_payload = payload
							}, new JsonSerializerOptions { WriteIndented = true });
						}
					}

					response.EnsureSuccessStatusCode();

					var result = await response.Content.ReadAsStringAsync();
					LogToDebug("Issue updated successfully");
					
					// Format the JSON response for better readability
					try
					{
						var jsonDocument = JsonDocument.Parse(result);
						var formattedJson = JsonSerializer.Serialize(jsonDocument, new JsonSerializerOptions { WriteIndented = true });
						LogToDebug("Update issue JSON response formatted successfully");
						return formattedJson;
					}
					catch (JsonException)
					{
						LogToDebug("Update issue response is not valid JSON, returning as-is");
						return result;
					}
				}
				catch (Exception ex)
				{
					LogToDebug($"Error in UpdateIssueAsync: {ex.Message}");
					return JsonSerializer.Serialize(new { error = $"Failed to update issue: {ex.Message}" }, new JsonSerializerOptions { WriteIndented = true });
				}
			}

			[McpTool(Description = "Posts a comment on a specific issue.")]
			public async Task<string> PostCommentOnIssueAsync(
				[McpParameter(true, "The unique ID of the project.")] string projectId,
				[McpParameter(true, "The unique ID of the issue.")] string issueId,
				[McpParameter(true, "The content of the comment.")] string body)
			{
				try
				{
					LogToDebug($"PostCommentOnIssueAsync called with projectId: {projectId}, issueId: {issueId}");

					var url = $"https://developer.api.autodesk.com/construction/issues/v1/projects/{projectId}/issues/{issueId}/comments";

					// Use flat structure for comments as well
					var payload = new
					{
						body = body
					};

					var content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");

					var currentToken = await GetValidToken();
					if (string.IsNullOrEmpty(currentToken))
					{
						LogToDebug("No valid token available");
						return JsonSerializer.Serialize(new { error = "Authentication required - please authenticate first" }, new JsonSerializerOptions { WriteIndented = true });
					}

					_client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", currentToken);

					LogToDebug("Sending POST request to create comment...");
					var response = await _client.PostAsync(url, content);

					LogToDebug($"Create comment response status: {response.StatusCode}");
					
					if (!response.IsSuccessStatusCode)
					{
						// Capture the actual error response body
						var errorContent = await response.Content.ReadAsStringAsync();
						LogToDebug($"Create Comment API Error Response: {errorContent}");
						LogToDebug($"Request URL was: {url}");
						LogToDebug($"Request payload was: {JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true })}");
						
						// Try to format error JSON if possible
						try
						{
							var errorJson = JsonDocument.Parse(errorContent);
							var formattedError = JsonSerializer.Serialize(errorJson, new JsonSerializerOptions { WriteIndented = true });
							LogToDebug($"Formatted Create Comment Error Response: {formattedError}");
							
							// Return the actual API error response instead of generic message
							return JsonSerializer.Serialize(new { 
								error = "Failed to create comment", 
								status_code = (int)response.StatusCode,
								status_description = response.StatusCode.ToString(),
								api_error_response = errorJson,
								request_url = url,
								request_payload = payload
							}, new JsonSerializerOptions { WriteIndented = true });
						}
						catch (JsonException)
						{
							// If error response is not JSON, return as text
							return JsonSerializer.Serialize(new { 
								error = "Failed to create comment", 
								status_code = (int)response.StatusCode,
								status_description = response.StatusCode.ToString(),
								api_error_response = errorContent,
								request_url = url,
								request_payload = payload
							}, new JsonSerializerOptions { WriteIndented = true });
						}
					}

					response.EnsureSuccessStatusCode();

					var result = await response.Content.ReadAsStringAsync();
					LogToDebug("Comment created successfully");
					
					// Format the JSON response for better readability
					try
					{
						var jsonDocument = JsonDocument.Parse(result);
						var formattedJson = JsonSerializer.Serialize(jsonDocument, new JsonSerializerOptions { WriteIndented = true });
						LogToDebug("Create comment JSON response formatted successfully");
						return formattedJson;
					}
					catch (JsonException)
					{
						LogToDebug("Create comment response is not valid JSON, returning as-is");
						return result;
					}
				}
				catch (Exception ex)
				{
					LogToDebug($"Error in PostCommentOnIssueAsync: {ex.Message}");
					return JsonSerializer.Serialize(new { error = $"Failed to create comment: {ex.Message}" }, new JsonSerializerOptions { WriteIndented = true });
				}
			}

			[McpTool(Description = "Gets comments for a specific issue.")]
			public async Task<string> GetIssueCommentsAsync(
				[McpParameter(true, "The unique ID of the project.")] string projectId,
				[McpParameter(true, "The unique ID of the issue.")] string issueId)
			{
				LogToDebug($"GetIssueCommentsAsync called with projectId: {projectId}, issueId: {issueId}");
				var url = $"https://developer.api.autodesk.com/construction/issues/v1/projects/{projectId}/issues/{issueId}/comments";
				return await MakeApiRequest(url);
			}

			/// <summary>
			/// A helper method to make the HTTP GET request and handle the response.
			/// </summary>
			private async Task<string> MakeApiRequest(string url)
			{
				try
				{
					LogToDebug($"Making API request to: {url}");

					// Only get token when we actually need to make an API call
					var currentToken = await GetValidToken();
					if (string.IsNullOrEmpty(currentToken))
					{
						LogToDebug("No valid token available");
						return JsonSerializer.Serialize(new { error = "Authentication required - please authenticate first" }, new JsonSerializerOptions { WriteIndented = true });
					}

					_client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", currentToken);

					LogToDebug("Sending HTTP request...");
					var response = await _client.GetAsync(url);

					LogToDebug($"Response status: {response.StatusCode}");
					
					if (!response.IsSuccessStatusCode)
					{
						// Capture the actual error response body
						var errorContent = await response.Content.ReadAsStringAsync();
						LogToDebug($"API Error Response: {errorContent}");
						LogToDebug($"Response Headers: {response.Headers}");
						
						// Try to format error JSON if possible
						try
						{
							var errorJson = JsonDocument.Parse(errorContent);
							var formattedError = JsonSerializer.Serialize(errorJson, new JsonSerializerOptions { WriteIndented = true });
							LogToDebug($"Formatted Error Response: {formattedError}");
							
							// Return the actual API error response instead of generic message
							return JsonSerializer.Serialize(new { 
								error = "API request failed", 
								status_code = (int)response.StatusCode,
								status_description = response.StatusCode.ToString(),
								api_error_response = errorJson,
								request_url = url
							}, new JsonSerializerOptions { WriteIndented = true });
						}
						catch (JsonException)
						{
							// If error response is not JSON, return as text
							return JsonSerializer.Serialize(new { 
								error = "API request failed", 
								status_code = (int)response.StatusCode,
								status_description = response.StatusCode.ToString(),
								api_error_response = errorContent,
								request_url = url
							}, new JsonSerializerOptions { WriteIndented = true });
						}
					}
					
					response.EnsureSuccessStatusCode();

					var result = await response.Content.ReadAsStringAsync();
					LogToDebug($"Response received, length: {result.Length}");
					
					// Format the JSON response for better readability
					try
					{
						var jsonDocument = JsonDocument.Parse(result);
						var formattedJson = JsonSerializer.Serialize(jsonDocument, new JsonSerializerOptions { WriteIndented = true });
						LogToDebug("JSON response formatted successfully");
						return formattedJson;
					}
					catch (JsonException)
					{
						LogToDebug("Response is not valid JSON, returning as-is");
						return result;
					}
				}
				catch (HttpRequestException ex)
				{
					LogToDebug($"HTTP request failed: {ex.Message}");
					LogToDebug($"Request URL was: {url}");
					
					// Try to get more detailed error information
					if (ex.Data.Contains("StatusCode"))
					{
						LogToDebug($"HTTP Status Code: {ex.Data["StatusCode"]}");
					}
					
					return JsonSerializer.Serialize(new { error = $"API request failed: {ex.Message}" }, new JsonSerializerOptions { WriteIndented = true });
				}
				catch (Exception ex)
				{
					LogToDebug($"Unexpected error in MakeApiRequest: {ex.Message}");
					LogToDebug($"Request URL was: {url}");
					return JsonSerializer.Serialize(new { error = $"Unexpected error: {ex.Message}" }, new JsonSerializerOptions { WriteIndented = true });
				}
			}

			private async Task<string> GetValidToken()
			{
				try
				{
					if (_tokenHandler == null)
					{
						LogToDebug("Token handler is null");
						return null;
					}

					return await _tokenHandler.GetAccessTokenAsync();
				}
				catch (Exception ex)
				{
					LogToDebug($"Error getting token: {ex.Message}");
					return null;
				}
			}
		}

	}

	// APS configuration class
	public class APS
	{
		public string ClientId { get; set; }
		public string ClientSecret { get; set; }
		public string RedirectUri { get; set; }
	}

	public class CustomAttribute
	{
		public string AttributeDefinitionId { get; set; }
		public string Value { get; set; }
	}

	// OAuth handler and token management
	public class TokenHandler
	{
		private string _currentAccessToken;
		private string _refreshToken;
		private DateTime _tokenExpiryTime;
		private readonly APS _apsConfig;
		private readonly object _lockObject = new object();
		private HttpListener _httpListener = null;
		private static readonly AuthenticationClient authenticationClient = new AuthenticationClient();
		private readonly string APS_PORT = Environment.GetEnvironmentVariable("APS_PORT") ?? "5001";
		private readonly string FORGE_CALLBACK;
		private static readonly List<Scopes> _Scopes = new List<Scopes>()
		{
			Scopes.AccountRead,
			Scopes.DataCreate,
			Scopes.DataWrite,
			Scopes.DataRead,
			Scopes.BucketRead
		};

		public TokenHandler(APS apsConfig)
		{
			_apsConfig = apsConfig;
			FORGE_CALLBACK = Environment.GetEnvironmentVariable("FORGE_CALLBACK") ?? $"http://localhost:{APS_PORT}/api/aps/callback/oauth";
			Program.LogToDebug($"TokenHandler initialized with callback: {FORGE_CALLBACK}");
		}

		public async Task<string> GetAccessTokenAsync()
		{
			Program.LogToDebug("GetAccessTokenAsync called");

			// First check for environment variable token (from Mini-Hub)
			string envToken = Environment.GetEnvironmentVariable("APS_ACCESS_TOKEN");
			if (!string.IsNullOrEmpty(envToken))
			{
				Program.LogToDebug("Using access token from environment variable");
				Program.LogToDebug($"Token length: {envToken.Length} characters");
				lock (_lockObject)
				{
					_currentAccessToken = envToken;
					// Set a future expiry time since we don't know the exact expiry
					_tokenExpiryTime = DateTime.Now.AddHours(1);
				}
				return _currentAccessToken;
			}

			lock (_lockObject)
			{
				if (!string.IsNullOrEmpty(_currentAccessToken) && DateTime.Now.AddMinutes(5) < _tokenExpiryTime)
				{
					Program.LogToDebug("Using existing valid token");
					return _currentAccessToken;
				}
			}

			Program.LogToDebug("Need to authenticate - starting login process");
			await LoginAsync();
			return _currentAccessToken;
		}

		public string GetCurrentToken()
		{
			lock (_lockObject)
			{
				if (string.IsNullOrEmpty(_currentAccessToken) || DateTime.Now.AddMinutes(5) >= _tokenExpiryTime)
				{
					return null;
				}
				return _currentAccessToken;
			}
		}

		private async Task LoginAsync()
		{
			var tcs = new TaskCompletionSource<string>();

			try
			{
				Program.LogToDebug("Starting OAuth login process");

				_httpListener = new HttpListener();
				_httpListener.Prefixes.Add(FORGE_CALLBACK.Replace("localhost", "+") + "/");
				_httpListener.Start();

				Program.LogToDebug($"HTTP listener started on {FORGE_CALLBACK}");

				string oauthUrl = authenticationClient.Authorize(_apsConfig.ClientId, ResponseType.Code,
					redirectUri: FORGE_CALLBACK, scopes: _Scopes);

				Program.LogToDebug($"Opening browser for authentication: {oauthUrl}");

				// Try to open browser
				try
				{
					Process.Start(new ProcessStartInfo(oauthUrl) { UseShellExecute = true });
				}
				catch (Exception ex)
				{
					Program.LogToDebug($"Failed to open browser: {ex.Message}");
					Program.LogToDebug($"Please manually open this URL: {oauthUrl}");
				}

				var contextTask = _httpListener.GetContextAsync();
				var timeoutTask = Task.Delay(TimeSpan.FromMinutes(5));

				var completedTask = await Task.WhenAny(contextTask, timeoutTask);

				if (completedTask == timeoutTask)
				{
					throw new TimeoutException("Authentication timed out after 5 minutes");
				}

				var context = await contextTask;
				string code = context.Request.QueryString["code"];

				var responseString = "<html><body><h2>Login Success</h2><p>You can now close this window!</p></body></html>";
				byte[] buffer = Encoding.UTF8.GetBytes(responseString);
				var response = context.Response;
				response.ContentType = "text/html";
				response.ContentLength64 = buffer.Length;
				response.StatusCode = 200;
				await response.OutputStream.WriteAsync(buffer, 0, buffer.Length);
				response.OutputStream.Close();

				if (!string.IsNullOrEmpty(code))
				{
					Program.LogToDebug("Exchanging authorization code for access token");
					var bearer = await authenticationClient.GetThreeLeggedTokenAsync(_apsConfig.ClientId, code, FORGE_CALLBACK, _apsConfig.ClientSecret);
					UpdateToken(bearer);
					tcs.SetResult(_currentAccessToken);
				}
				else
				{
					throw new InvalidOperationException("No authorization code received");
				}
			}
			catch (Exception ex)
			{
				Program.LogToDebug($"Login failed: {ex.Message}");
				tcs.SetException(ex);
			}
			finally
			{
				_httpListener?.Stop();
			}

			await tcs.Task;
		}

		private void UpdateToken(ThreeLeggedToken bearer)
		{
			if (bearer == null)
			{
				throw new InvalidOperationException("Authentication failed. Bearer token is null.");
			}

			lock (_lockObject)
			{
				_currentAccessToken = bearer.AccessToken;
				_refreshToken = bearer.RefreshToken;
				_tokenExpiryTime = DateTime.Now.AddSeconds(double.Parse(bearer.ExpiresIn.ToString()));
				Program.LogToDebug($"Token acquired successfully. Expires at: {_tokenExpiryTime}");
			}
		}
	}

}

