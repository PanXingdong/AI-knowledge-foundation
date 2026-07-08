# feat: add remote Knowledge Hub API with multi-tenant support and VS Code integration

## Summary
This PR introduces a remote Knowledge Hub API that supports multiple knowledge bases, bearer token authentication, and seamless integration with VS Code extension.

## Changes

### Core API Enhancements (src/agent_knowledge_hub/service.py)
- **Multi-tenant Knowledge Base Registry**: Support for managing multiple knowledge bases via `KNOWLEDGE_BASES_JSON` or `KNOWLEDGE_BASES_CONFIG` environment variables
- **Bearer Token Authentication**: Optional token-based authentication for remote access control
- **New Remote Context Pack Endpoint**: `/api/knowledge-bases/{knowledge_base_id}/context-pack` for tenant-specific queries
- **Metadata Filtering**: Support for filtering search results by document metadata
- **Feishu Message Formatting Integration**: Reuse existing `MessageFormatter` for consistent output formatting

### Test Coverage (tests/test_service_api.py)
- Added comprehensive test for remote context pack API endpoint
- Validates Feishu-formatted context retrieval with proper authentication headers
- Tests knowledge base isolation and token validation

### VS Code Integration (integrations/vscode-knowledge-hub/)
- New directory containing VS Code extension for local development
- Provides IDE-native access to Knowledge Hub APIs
- Supports multi-tenant switching and query history

### Deployment Script (scripts/start-knowledge-hub-remote.sh)
- Production-ready bash script for starting remote Knowledge Hub server
- Configurable bind host/port, knowledge base ID, processed directory, and auth token
- Automatic port conflict detection and graceful restart
- Environment variable compatibility with existing Feishu bot deployment
- Built-in LAN IP discovery for easy team collaboration
- VS Code settings template generation

## Key Features
1. **Multi-Tenant Support**: Multiple teams can share a single Knowledge Hub instance with isolated data
2. **Secure Remote Access**: Bearer token authentication prevents unauthorized access
3. **IDE Integration**: Developers can query knowledge bases directly from VS Code
4. **Backward Compatible**: Existing Feishu bot and local CLI workflows remain unchanged
5. **Flexible Configuration**: Environment-driven configuration supports various deployment scenarios

## Testing
- All existing tests pass
- New test validates remote API functionality
- Manual testing completed for VS Code integration

## Deployment Notes
- Set `KNOWLEDGE_HUB_API_TOKEN` environment variable for production deployments
- Use `scripts/start-knowledge-hub-remote.sh` for easy server startup
- VS Code users should configure `knowledgeHub.baseUrl` and `knowledgeHub.token` in workspace settings
