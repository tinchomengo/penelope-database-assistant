from typing import Optional, List, Dict, Any
from flask import Flask, request, jsonify
from langchain_core.tools import tool, Tool
from datetime import timedelta, datetime
from langchain.llms.base import LLM
from operator import itemgetter
from abacusai import ApiClient
from flask_cors import CORS
from pydantic import Field
import requests
import dotenv
import os
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_google_community import GoogleSearchAPIWrapper
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain.tools.render import render_text_description
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import (
    Runnable,
    RunnableLambda,
    RunnableMap,
    RunnablePassthrough,
)
from langchain_core.prompts.chat import MessagesPlaceholder
from langchain_postgres import PostgresChatMessageHistory
import uuid
import psycopg



# Load environment variables from a .env file
dotenv.load_dotenv()
session_id = str(uuid.uuid4())

# TODO: create a database called chat_history
conn_info =  "postgresql://postgres:postgres@localhost/chat_history"
table_name = "chat_history"
sync_connection = psycopg.connect(conn_info)

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

coingecko_headers = {
            "Content-Type": "application/json",
            "x-cg-pro-api-key": COINGECKO_API_KEY,
        }

# --------------------- CUSTOM MODEL ABACUS ---------------------------------------

class AbacusAIClient:
    def __init__(self, api_key: str, deployment_token: str, deployment_id: str):
        self.client = ApiClient(api_key=api_key)
        self.deployment_token = deployment_token
        self.deployment_id = deployment_id

    def ask_model(self, prompt: str) -> Optional[str]:
        """
        Send a query/prompt to an Abacus.AI model for inference.

        Parameters:
        prompt (str): The query/prompt to send to the model.

        Returns:
        Optional[str]: The response from the model as a string, or None if there was an error.
        """
        try:
            response = self.client.get_chat_response(
                deployment_id=self.deployment_id,
                deployment_token=self.deployment_token,
                messages=[{"is_user": True, "text": prompt}]
            )

            base_result = response['messages'][1]['text']
            result_text = f'{base_result}'

            search_results = response['search_results']
            for result in search_results:
                data_result = result['results']
                for data_item in data_result:
                    answer = data_item['answer']
                    # result_text += answer
            
            return result_text
        except Exception as e:
            print(f"Abacus error: {e}")
            return None


# --------------------- ABACUS CUSTOM MODEL + LANGCHAIN -------------------------------

class CustomAbacusLLM(LLM):

    abacus_client = Field(None, alias='abacus_client')

    def __init__(self, abacus_client: AbacusAIClient, **kwargs):
        super().__init__(**kwargs)
        self.abacus_client = abacus_client

    def _call(self, prompt: str, stop: Optional[List[str]] = None) -> str:
        """
        Call the Abacus.AI model with a prompt.

        Parameters:
        prompt (str): The prompt to send to the model.
        stop (Optional[List[str]]): Optional stop sequences.

        Returns:
        str: The response from the model.
        """
        # print("Custom_abacus_prompt:", prompt)
        response = self.abacus_client.ask_model(prompt=prompt)
        if response is None:
            raise ValueError("Error in model response")
        return response

    @property
    def _identifying_params(self) -> dict:
        return {"model_name": "penelope"}

    @property
    def _llm_type(self) -> str:
        return "penelope"


# ------------------------ TOOLS LANGCHAIN ------------------------------------------

tavily_search = TavilySearchResults()
google_search = GoogleSearchAPIWrapper(google_api_key=GOOGLE_API_KEY, google_cse_id=GOOGLE_CSE_ID)

google_search_tool = Tool(
    name="google_search",
    description="Search Google for recent results.",
    func=google_search.run,
)


# function to provide a default value for sorting
def get_token_symbol(item):
    token_symbol = item.get('tokenSymbol')
    return token_symbol if token_symbol is not None else ''

@tool
def get_llama_chains(token_symbol):
    """
    Retrieves information about chains from the DefiLlama API and searches for a specific protocol based on its token symbol.

    Parameters:
    token_symbol (str): The token symbol of the protocol to search for.

    Returns:
    dict: A dictionary containing information about the protocol if found (including its ID, name, and TVL), or a message indicating the result of the search.
    """

    url = "https://api.llama.fi/v2/chains"
    
    try:
        formatted_symbol = str(token_symbol).casefold()
        response = requests.get(url)

        if response.status_code == 200:
            chains = response.json()
            sorted_data = sorted(chains, key=get_token_symbol)

            for chain in sorted_data:
                if formatted_symbol == str(chain['tokenSymbol']).casefold():
                    return f"current tvl of {chain['name']} is {chain['tvl']}"
            
            return "Protocol not found"
        
        return 'Unable to fetch the data. Please check the token name and try again.'
    
    except requests.RequestException as e:
        return 'Unable to fetch the data. Please check the token name and try again.'
    
    except Exception as e:
        return 'Unable to fetch the data. Please check the token name and try again.'


@tool
def get_fees_revenue_all_protocols(token_name):
    """
    Retrieves fees and revenue data for all protocols from the DefiLlama API for a specified token.

    Parameters:
    token_name (str): The name of the token for which fees and revenue data is requested.

    Returns:
    dict or str: A dictionary containing the fees and revenue data if the request is successful,
                 or an error message if the request fails.

    The function makes a GET request to the DefiLlama API to fetch daily fees and revenue data for the specified token.
    It extracts and returns the relevant data in a structured dictionary format if the request is successful.
    """
    
    url = f"https://api.llama.fi/overview/fees/{token_name}?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true&dataType=dailyFees"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            protocols_data = {
                'chain': data.get('chain', None),
                'dailyRevenue': data.get('dailyRevenue', None),
                'dailyUserFees': data.get('dailyUserFees', None),
                'dailyHoldersRevenue': data.get('dailyHoldersRevenue', None),
                'dailyProtocolRevenue': data.get('dailyProtocolRevenue', None),
            }
            return protocols_data
        else:
            return 'Unable to fetch the data. Please check the token name and try again.'
    except Exception as e:
        return 'Unable to fetch the data. Please check the token name and try again.'

@tool
def get_latest_bitcoin_news(token_name):
    """
    Retrieves articles related to the specified token from a given API endpoint and returns the content of each article.

    Parameters:
    token_name (str): The name of the token for which to retrieve articles. Expected to be "bitcoin" for bot_id 1.

    Returns:
    list of str: A list containing the content of each article retrieved from the API.
    """
    
    # Define the bot_id for Bitcoin
    bot_id = 1
    limit = 10
    
    # Construct the URL for the API request
    url = f"https://zztc5v98-5001.uks1.devtunnels.ms/get_articles?bot_id={bot_id}&limit={limit}"
    
    try:
        # Make the API request
        response = requests.get(url)
        
        # Check if the request was successful
        if response.status_code == 200:
            data = response.json().get('data', [])
            
            # Extract the content from each article
            articles_content = [article['content'] for article in data]
            
            return articles_content
        else:
            return f"Unable to fetch the data. HTTP Status Code: {response.status_code}"
    
    except Exception as e:
        return f"An error occurred: {str(e)}. Please try again later."
    

@tool
def get_token_data(coin):
    """
    Fetch detailed data about a cryptocurrency token from the CoinGecko API.

    The function retrieves the current price, market cap, total volume, and various other details
    of the specified cryptocurrency token. It also fetches historical price data from one year ago
    to calculate the price change over the past year.

    Parameters:
    coin (str): The identifier (name or symbol) of the cryptocurrency token.

    Returns:
    dict: A dictionary containing various details about the cryptocurrency token, including:
        - id: The CoinGecko ID of the token.
        - symbol: The symbol of the token.
        - logo: The URL of the token's logo.
        - description: A brief description of the token.
        - market_cap_usd: The market capitalization of the token in USD.
        - total_volume: The total trading volume of the token in USD.
        - website: The official website URL of the token.
        - total_supply: The total supply of the token.
        - circulating_supply: The circulating supply of the token.
        - percentage_circulating_supply: The percentage of the circulating supply relative to the total supply.
        - max_supply: The maximum supply of the token.
        - supply_model: The supply model (Inflationary or Deflationary).
        - current_price: The current price of the token in USD.
        - price_a_year_ago: The price of the token one year ago in USD.
        - price_change_percentage_1y: The percentage change in price over the past year.
        - ath: The all-time high price of the token in USD.
        - ath_change_percentage: The percentage change from the all-time high price.
        - coingecko_link: The URL to the token's page on CoinGecko.
        - categories: A comma-separated string of the token's categories.
        - chains: A comma-separated string of the ecosystems the token is part of.
        - contracts: A string listing the contract addresses of the token on various platforms.
        - fully_diluted_valuation: The fully diluted market valuation of the token in USD.
        - success: A boolean indicating the success of the API call.

    If there is an error during the API call or data processing, the function will print an error message
    and return None.
    """
    try:
        # Get today's date
        current_date = datetime.now()

        # Calculate the date one year ago
        one_year_ago = current_date - timedelta(days=365)
        formatted_date = one_year_ago.strftime('%d-%m-%Y')

        formatted_coin = str(coin).casefold().strip()
        response = requests.get(f'{COINGECKO_BASE_URL}/coins/{formatted_coin}', headers=coingecko_headers)
        historical_response = requests.get(f'{COINGECKO_BASE_URL}/coins/{formatted_coin}/history?date={formatted_date}', headers=coingecko_headers)
      
        if response.status_code == 200 and historical_response.status_code == 200:
            response = response.json()
            historical_response = historical_response.json()

            id = response.get('id')
            symbol = response.get('symbol')
            description = response['description']['en'] if 'description' in response and 'en' in response['description'] else None

            logo = response['image']['small'] if 'image' in response and 'small' in response['image'] else None

            market_cap_usd = response['market_data']['market_cap']['usd'] \
                if 'market_data' in response and 'market_cap' in response['market_data'] \
                and 'usd' in response['market_data']['market_cap'] else None

            total_volume = response['market_data']['total_volume']['usd'] \
                if 'market_data' in response and 'total_volume' in response['market_data'] \
                and 'usd' in response['market_data']['total_volume'] else None

            website = next((link for link in response.get('links', {}).get('homepage', []) if link.strip()), None)

            total_supply = response['market_data'].get('total_supply')

            circulating_supply = response['market_data'].get('circulating_supply')

            percentage_circulating_supply = (float(circulating_supply) / float(total_supply)) * 100 \
                if total_supply and circulating_supply else None

            max_supply = response['market_data'].get('max_supply')

            supply_model = 'Inflationary' if max_supply is None else 'Deflationary'

            current_price = response['market_data']['current_price']['usd'] \
                if 'market_data' in response and 'current_price' in response['market_data'] \
                and 'usd' in response['market_data']['current_price'] else None

            ath = response['market_data']['ath']['usd'] \
                if 'market_data' in response and 'ath' in response['market_data'] \
                and 'usd' in response['market_data']['ath'] else None

            ath_change_percentage = response['market_data']['ath_change_percentage']['usd'] \
                if 'market_data' in response and 'ath_change_percentage' in response['market_data'] \
                and 'usd' in response['market_data']['ath_change_percentage'] else None

            coingecko_link = f"https://www.coingecko.com/en/coins/{id}"

            categories = ", ".join([category for category in response.get("categories", [])
                                    if 'ecosystem' not in category.lower()]) or None

            chains = ", ".join([category for category in response.get("categories", [])
                                if 'ecosystem' in category.lower()]) or None

            contracts = ""
            if 'platforms' in response and response['platforms']:
                for platform, contract_address in response['platforms'].items():
                    if platform and contract_address:  # Check if both platform and contract_address are not empty
                        contracts += f"{platform}: {contract_address}\n"

            fully_diluted_valuation = response['market_data']['fully_diluted_valuation']['usd'] \
                if 'market_data' in response and 'fully_diluted_valuation' in response['market_data'] \
                and 'usd' in response['market_data']['fully_diluted_valuation'] else None

            price_a_year_ago = historical_response['market_data']['current_price']['usd']\
                if 'market_data' in historical_response and 'current_price' in historical_response['market_data']\
                and 'usd' in historical_response['market_data']['current_price'] else None

            price_change_percentage_1y = response['market_data']['price_change_percentage_1y']\
                if 'market_data' in response and 'price_change_percentage_1y' in response['market_data'] else None

            return {
                'id': id,
                'symbol': symbol,
                'logo': logo,
                'description': description,
                'market_cap_usd': market_cap_usd,
                'total_volume': total_volume,
                'website': website,
                'total_supply': total_supply,
                'circulating_supply': circulating_supply,
                'percentage_circulating_supply': percentage_circulating_supply,
                'max_supply': max_supply,
                'supply_model': supply_model,
                'current_price': current_price,
                'price_a_year_ago': price_a_year_ago,
                'price_change_percentage_1y': price_change_percentage_1y,
                'ath': ath,
                'ath_change_percentage': ath_change_percentage,
                'coingecko_link': coingecko_link,
                'categories': categories,
                'chains': chains,
                'contracts': contracts,
                'fully_diluted_valuation': fully_diluted_valuation,
                'success': True
            }
        else:
            return None
    except Exception as e:
        print(f'Coingecko error: {str(e)}')
        return None


@tool
def multiply(first_int: int, second_int: int) -> int:
    """
    Multiply two integers together.

    Parameters:
    first_int (int): The first integer.
    second_int (int): The second integer.

    Returns:
    int: The product of the two integers.
    """
    return first_int * second_int


@tool
def add(first_int: int, second_int: int) -> int:
    "Add two integers."
    return first_int + second_int


@tool
def exponentiate(base: int, exponent: int) -> int:
    "Exponentiate the base to the exponent power."
    return base**exponent


# ------------------------------ Perplexity ----------------------------------------

def perplexity_api_request(question, content, prompt=None, model='llama-3-sonar-large-32k-online'):
    
    url = "https://api.perplexity.ai/chat/completions"
    prompt = prompt if prompt else """
    you are an AI Asistant, called Penelope, you are very polite and smart, an expert in creating analysis, writing summaries.
                                    """
    
    content = f""""create a response for this question or prompt {question} taking into account the following text: {content}, Create a nice and well structure response."""

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": prompt
            },
            {
                "role": "user",
                "content": content
            }
        ]
    }

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
       
        response.raise_for_status()  

        choices = response.json().get('choices', [])
        if choices:
            assistant_message = choices[0].get('message', {})
            answer_content = assistant_message.get('content', None)
            
            if answer_content:
                return answer_content
            else:
                return "Apologies, it seems to be a problem, please try again"
        else:
            return "Apologies, it seems to be a problem, please try again"
    
    except requests.exceptions.RequestException as err:
        return "Apologies, it seems to be a problem, please try again"


# ---------------------------- PENELOPE ------------------------------------------

class Penelope:
    def __init__(self, api_key: str, deployment_token: str, deployment_id: str, tools: List, table_name: str, session_id: str, sync_connection):
        # Initialize the database table
        cur = sync_connection.cursor()
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE  table_schema = 'public'
                AND    table_name   = %s
            );
        """, (table_name,))
        table_exists = cur.fetchone()[0]

        if table_exists:
            print(f"---Table {table_name} already exists---")
        else:
            print(f"Table {table_name} does not exist, creating it...")
            # Create the table schema
            PostgresChatMessageHistory.create_tables(sync_connection, table_name)

        # Initialize the message history
        self.history = PostgresChatMessageHistory(
            table_name,
            session_id,
            sync_connection=sync_connection
        )

        # Initialize the Penelope attributes
        self.abacus_client = AbacusAIClient(
            api_key=api_key,
            deployment_token=deployment_token,
            deployment_id=deployment_id
        )
        self.chat_history = []
        self.penelope = CustomAbacusLLM(self.abacus_client)
        self.tools = tools
        self.tool_map = {tool.name: tool for tool in tools}
        self.rendered_tools = render_text_description(tools)
        self.system_prompt = f"""You are an assistant that has access to the following set of tools. Here are the names and descriptions for each tool:
                                {self.rendered_tools}
                                Given the user input, return the name and input of the tool to use if any helps. Return your response as a JSON blob with 'name' and 'arguments' keys."""

        self.prompt_template = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                MessagesPlaceholder(variable_name="chat_history"),
                ("user", "{input}")
            ]
        )

    def tool_chain(self, model_output):
        chosen_tool = self.tool_map[model_output["name"]]
        return itemgetter("arguments") | chosen_tool

    def call_tools(self, msg: AIMessage) -> Runnable:
        """Simple sequential tool calling helper."""
        print('msg: ', msg)
        tool_calls = msg.tool_calls.copy()
        for tool_call in tool_calls:
            tool_call["output"] = self.tool_map[tool_call["name"]].invoke(tool_call["args"])
        return tool_calls

    def trim_messages(self, chain_input):
        stored_messages = self.history.messages
        print("\nstored_messages: ", stored_messages)
        if len(stored_messages) <= 2:
            return RunnablePassthrough()

        self.history.clear()

        for message in stored_messages[-2:]:
            self.history.add_user_message(message)

        return RunnablePassthrough()

    def process_input(self, input: str) -> Any:
        try:  
            start = datetime.now()
            print('Start time: ', start)
            
            chain = self.prompt_template | self.penelope

            # chain = self.prompt_template | self.penelope | JsonOutputParser() | self.tool_chain
            chain_with_message_history = RunnableWithMessageHistory(
                                            chain,
                                            lambda session_id: self.history,
                                            input_messages_key="input",
                                            history_messages_key="chat_history",
                                        )

            chain_with_trimming = (
                RunnablePassthrough.assign(messages_trimmed=self.trim_messages)
                | chain_with_message_history
            )

            result = chain_with_message_history.invoke(
                {"input": input},
                {"configurable": {"session_id": uuid.uuid4()}},
            )

            # print("result: ", result)
            final_response = perplexity_api_request(content=str(result), question=input)

            # Add messages to the chat history
            self.history.add_messages([
                SystemMessage(content=self.system_prompt),
                AIMessage(content=final_response),
                HumanMessage(content=input),
            ])

            end = datetime.now()
            print('End time: ', end)
            print('Time spent:', end - start)
            
            return {'success': True, 'error': None, 'response': final_response}
        
        except Exception as e:
            return {'success': False, 'error': f'Error processing input: {str(e)}', 'response': None}


# Example usage:
tools = [get_token_data, get_llama_chains, get_latest_bitcoin_news]
ABACUS_API_KEY = ABACUS_API_KEY
ABACUS_MODEL_TOKEN = ABACUS_MODEL_TOKEN
DEPLOYMENT_ID = DEPLOYMENT_ID 

CUSTOM_LLM = Penelope(ABACUS_API_KEY, ABACUS_MODEL_TOKEN, DEPLOYMENT_ID, tools, table_name, session_id, sync_connection)

app = Flask(__name__)
CORS(app)

@app.route('/process', methods=['POST'])
def process():
    try:
        user_input = request.get_json()
        
        if not user_input:
            raise ValueError("No JSON data provided")
        
        # Assuming CUSTOM_LLM.process_input() returns a dictionary with 'response', 'error', and 'success' keys.
        output = CUSTOM_LLM.process_input(user_input)
        
        if output['success']:
            response = output['response']
        else:
            response = output['error']
        
        return jsonify({'response': response, 'success': output['success']})
    
    except ValueError as ve:
        return jsonify({'response': f"ValueError: {str(ve)}", 'success': False})
    
    except Exception as e:
        return jsonify({'response': f"Exception: {str(e)}", 'success': False})


@app.route('/')
def home():
    return "Penelope API is running"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, use_reloader=True)

