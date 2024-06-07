from typing import Optional, List, Dict, Any
from langchain_core.tools import tool, Tool
from datetime import timedelta, datetime
from langchain.llms.base import LLM
from operator import itemgetter
from abacusai import ApiClient
from pydantic import Field
import requests
import dotenv
import os
from langchain_openai import ChatOpenAI
from langchain_google_community import GoogleSearchAPIWrapper
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain.tools.render import render_text_description
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage
from langchain_core.runnables import (
    Runnable,
    RunnableLambda,
    RunnableMap,
    RunnablePassthrough,
)
import json

# Load environment variables from a .env file
dotenv.load_dotenv()

# Configuration
ABACUS_API_KEY = os.getenv('ABACUS_API_KEY')
ABACUS_MODEL_TOKEN = os.getenv('ABACUS_MODEL_TOKEN')
DEPLOYMENT_ID = '1209bcfb2c'
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
COINGECKO_BASE_URL = 'https://pro-api.coingecko.com/api/v3'

def format_output(output):
    prompt = f"Structure the following LLM output, removing symbols like 'backslashes' and non-reader friendly text, so that it is easily understandable by humans: {output}"
    chatbot = ChatOpenAI(openai_api_key=OPENAI_API_KEY)
    result = chatbot.invoke(prompt)
    
    # Print the full response for debugging
    print("Full response:", result)
    
    # Extract the content string
    content_str = result.content  # Adjust this if the structure of 'result' is different
    
    # Try to parse the content string as JSON
    try:
        content_json = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        content_json = None
    
    # Extract the 'response' field
    if content_json and 'response' in content_json:
        content = content_json['response']
    else:
        content = "Unexpected response format"
    
    return content

def replace_newline_symbols(text):
    return text.replace('\\n', '\n')

userOutput = content="Response: \nHi there, I'm Penelope. You've provided a detailed description of Bitcoin, which is a fascinating topic. Here's a structured summary of the information:\n\nOverview of Bitcoin\nBitcoin is the first successful internet money based on peer-to-peer technology. It was created by Satoshi Nakamoto and operates without a central bank or authority. The source code is publicly available as an open-source project.\n\nKey Features\n- Decentralized: Bitcoin is a decentralized peer-to-peer internet currency that allows for secure, verifiable, and immutable transactions.\n- Limited Supply: There will only be 21 million Bitcoins ever created, making it a deflationary currency.\n- Hashing Algorithm: Bitcoin uses the SHA-256 hashing algorithm with an average transaction confirmation time of 10 minutes.\n- Mining: Miners use ASIC chips dedicated to mining Bitcoin, resulting in a high hash rate.\n\nHistory and Impact\n- Inspiration: Bitcoin has inspired other alternative currencies like Litecoin, Peercoin, and Primecoin.\n- Smart Contracts: The innovation of Turing-complete smart contracts by Ethereum led to the development of projects like EOS, Tron, and even crypto-collectibles like CryptoKitties.\n\nMarket Information\n- Market Capitalization: The current market capitalization of Bitcoin is approximately $1.4 trillion USD.\n- Total Volume: The total volume is around $28.9 billion.\n- Website: You can find more information on Bitcoin at http://www.bitcoin.org.\n- Supply: The total supply is 21 million, with a circulating supply of around 19.7 million (93.85% of the total supply).\n- Current Price: The current price of Bitcoin is $71,149.\n- Price Change: The price has increased by 170.06% over the past year.\n- All-Time High: The all-time high price was $73,738, with a current change percentage of -3.55%.\n\nAdditional Resources\n- CoinGecko Link: You can find more information about Bitcoin on CoinGecko at https://www.coingecko.com/en/coins/bitcoin.\n- Categories: Bitcoin is categorized under FTX Holdings, Cryptocurrency, Proof of Work (PoW), Layer 1 (L1), and the GMCI 30 Index.\n\nI hope this summary helps you understand Bitcoin better. If you have any further questions, feel free to ask. Success: True' response_metadata={'token_usage': {'completion_tokens': 482, 'prompt_tokens': 581, 'total_tokens': 1063}, 'model_name': 'gpt-3.5-turbo', 'system_fingerprint': None, 'finish_reason': 'stop', 'logprobs': None} id='run-907ccf45-dacd-425f-a180-f7d531434b73-0' usage_metadata={'input_tokens': 581, 'output_tokens': 482, 'total_tokens': 1063}"
parsed_output = replace_newline_symbols(userOutput)
print("Parsed response: ",parsed_output)