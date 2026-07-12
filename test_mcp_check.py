import sys
sys.path.insert(0, r'C:\Users\jiangcheng_m.CYOU-INC\Desktop\akshare-jc-mcp\src')
from akshare_jc_mcp.server import mcp, get_data

# fastmcp stores tools internally, try to list them
print(f'MCP server: {mcp.name}')
print(f'get_data tool created: {get_data is not None}')
