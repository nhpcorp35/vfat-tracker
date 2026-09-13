"""
Checking whether Etherscan's V2 multichain API (tokennfttx, chainid=10
for Optimism) works keyless, or requires ETHERSCAN_API_KEY. Testing
directly rather than assuming either way.
"""
import requests

SICKLE_CUSTODY = "0x62aba0f25eb30993b577885b32c1b2a572000573"
NPM_OPTIMISM = "0xC36442b4a4522E871399CD717aBDD847Ab11FE88"

url = "https://api.etherscan.io/v2/api"
params = {
    "chainid": 10,
    "module": "account",
    "action": "tokennfttx",
    "address": SICKLE_CUSTODY,
    "contractaddress": NPM_OPTIMISM,
    "sort": "asc",
}
resp = requests.get(url, params=params, timeout=15)
print("Status code:", resp.status_code)
print("Response body:", resp.text[:2000])
