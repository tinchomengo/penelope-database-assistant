import os
import json
import time
import base64
import requests
from openai import OpenAI
from flask_cors import CORS
from dotenv import load_dotenv
from difflib import SequenceMatcher
from datetime import timedelta, datetime
from flask import Flask, request, jsonify, Response
from openai import APIError, RateLimitError, APIConnectionError


import io
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


# Load environment variables
load_dotenv()
OPENAI_KEY = os.getenv('OPENAI_API_KEY')
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
COINGECKO_BASE_URL = 'https://pro-api.coingecko.com/api/v3'

coingecko_headers = {
            "Content-Type": "application/json",
            "x-cg-pro-api-key": COINGECKO_API_KEY,
        }


# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_KEY)


# -------------------------- GOOGLE DRIVE ------------------------------------------

class Google_drive:
    def __init__(self, credentials):
        self.credentials = credentials

    def init_drive_client(credentials: str):
        """
        Initiates the Google Drive API client by handling the authorization flow and returning the service object.
        """
        creds = None
        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first time.
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json")
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    credentials
                )
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open("token.json", "w") as token:
                token.write(creds.to_json())
        
        try:
            service = build("drive", "v3", credentials=creds)
            return service
        except HttpError as error:
            return None

    def get_folders_and_files(self, service, folder_names):
        """
        Connects to the Google Drive API client, finds all folders matching the specified names (case-insensitive),
        recursively retrieves all files and subfolders inside them with additional metadata,
        and attempts to read the content of each file.
        Returns a list of dictionaries with folder name, id, files/subfolders inside, and file contents.
        Saves the result to a JSON file.
        """
        folders_and_files = []
        local_paths = []

        try:
            for folder_name in folder_names:
                folder_results = service.files().list(
                    q=f"mimeType='application/vnd.google-apps.folder' and name contains '{folder_name.lower()}'",
                    spaces='drive',
                    fields="files(id, name)"
                ).execute()

                folders = folder_results.get("files", [])

                if not folders:
                    print(f"No folders found with name '{folder_name}'.")
                    continue

                for folder in folders:
                    if folder['name'].lower() != folder_name.lower():
                        continue
                
                    folder_dict, local_path = get_folder_contents(service, folder['id'], folder['name'], "")
                    print('local_path: ', local_path)
                    folders_and_files.append(folder_dict)
                    local_paths.append(local_path)

            # Save to JSON file
            with open('folders_and_files.json', 'w', encoding='utf-8') as f:
                json.dump(folders_and_files, f, indent=2, ensure_ascii=False)

            print("Folder information saved to 'folders_and_files.json'")
            return folders_and_files

        except HttpError as error:
            print(f"An error occurred: {error}")
            return []

    def get_folder_contents(service, folder_id, folder_name, current_path=""):
        """Recursively get contents of a folder and read file contents."""
        folder_dict = {
            "folder_name": folder_name,
            "folder_id": folder_id,
            "contents": []
        }
    
        # Update the current path
        new_path = f"{current_path}/{folder_name}" if current_path else folder_name

        results = service.files().list(
            q=f"'{folder_id}' in parents",
            spaces='drive',
            fields="files(id, name, mimeType, fullFileExtension, size, modifiedTime, createdTime, webViewLink)"
        ).execute()

        items = results.get("files", [])
        local_path = ''

        for item in items:
            item_type = get_file_type(item['mimeType'])
            size_mb = convert_size_to_mb(item.get('size'))
            
            if size_mb is not None and size_mb > 500:
                print(f"Skipping large file: {item['name']} (Size: {size_mb:.2f} MB)")
                continue

            item_dict = {
                "name": item['name'],
                "id": item['id'],
                "type": item_type,
                "mimeType": item['mimeType'],
                "fullFileExtension": item.get('fullFileExtension', ''),
                "size": f"{size_mb:.2f} MB" if size_mb is not None else 'N/A',
                "modifiedTime": item.get('modifiedTime'),
                "createdTime": item.get('createdTime'),
                "webViewLink": item.get('webViewLink', ''),
                "google_drive_path": f"{new_path}/{item['name']}",
            }

            if item_type == 'folder':
                sub_folder_dict, _ = get_folder_contents(service, item['id'], item['name'], new_path)
                item_dict.update(sub_folder_dict)
            else:            
                new_path = transform_string(new_path)
                local_path = f"penelope-database-assistant/downloads/{new_path}"
                item_dict['file_path'] = local_path

                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                res = download_file(service, item['id'], item['name'], local_path, item['mimeType'])
                if not res:
                    continue
            
            folder_dict["contents"].append(item_dict)

        return folder_dict, local_path

    def convert_size_to_mb(size_str):
        """Convert size from bytes string to megabytes float."""
        try:
            size_bytes = int(size_str)
            return size_bytes / (1024 * 1024)  # Convert bytes to MB
        except (ValueError, TypeError):
            return None

    def get_file_type(mime_type):
        """Helper function to determine file type based on MIME type."""
        mime_type = str(mime_type).casefold()
        if mime_type == 'application/vnd.google-apps.folder':
            return 'folder'
        elif 'vnd.openxmlformats-officedocument.wordprocessingml.document' in mime_type:
            return 'docx'
        elif 'pdf' in mime_type:
            return 'pdf'
        elif 'image' in mime_type:
            return 'image'
        elif 'vnd.google-apps.spreadsheet' in mime_type:
            return 'sheet'
        elif 'vnd.google-apps.document' in mime_type:
            return 'gdoc'
        else:
            return 'other'

    def download_file(service, file_id, file_name, file_path, mimeType):
        print(f"\nAttempting to download: {file_name}")
        print('Image - mimeType: ', mimeType)
        file_extension = '.pdf'
        if mimeType == 'image/png':
            file_extension = '.png'
        if mimeType == 'text/plain':
            file_extension = '.txt'
        if mimeType == 'image/jpeg':
            file_extension = '.jpg'

        try:
            # First, try to get the file directly
            request = service.files().get_media(fileId=file_id)
            # Execute the request to get the response
            request.execute()
            
        except HttpError as error:
            if error.resp.status == 403:
                # If direct download fails, try to export as PDF
                try:
                    request = service.files().export_media(fileId=file_id, mimeType='application/pdf')
                    print(f" --- Exporting {file_name} as PDF ---")
                except HttpError as export_error:
                    print(f"Failed to export {file_name}: {export_error}")
                    return False
            else:
                print(f"Error downloading {file_name}: {error}")
                return False

        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            try:
                status, done = downloader.next_chunk()
                print(f"--- Download {int(status.progress() * 100)}% complete ---")
            except HttpError as error:
                print(f"An error occurred: {error}")
                return False

        # Ensure the directory exists
        os.makedirs(file_path, exist_ok=True)

        # Create a safe filename
        safe_filename = "".join([c for c in file_name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).rstrip()
        full_path = os.path.join(file_path, f"{transform_string(safe_filename)}{file_extension}")

        try:
            with open(full_path, 'wb') as f:
                f.write(fh.getvalue())
            print(f"\n --- File saved: {full_path} ---")
            return True
        except IOError as error:
            print(f"Error saving file {full_path}: {error}")
            return False

    def check_file(file_path):
        """
        Check if a file exists and retrieve its last modified time.

        Args:
        - file_path (str): The path to the file to be checked.

        Returns:
        - file_info (dict): Dictionary containing file information:
        {'path': file_path (str), 'exists': exists (bool), 'last_modified': last_modified (datetime)}
        """
        file_info = {
            'path': file_path,
            'exists': False,
            'last_modified': None
        }

        if os.path.exists(file_path):
            file_info['exists'] = True
            last_modified_timestamp = os.path.getmtime(file_path)
            file_info['last_modified'] = datetime.fromtimestamp(last_modified_timestamp)

        return file_info

# Example usage:
# file_path = 'C:\Users\David\Documents\AI Alpha\penelope-database-assistant\penelope-database-assistant\downloads\database_assistant\database\render_(rndr)_database\render_(rndr)_analysis\Copy of Render RNDR Quick Analysis - May 23th.pdf'
# file_info = check_file(file_path)

# print(f"File: {file_info['path']}")
# print(f"Exists: {file_info['exists']}")
# if file_info['exists']:
#     print(f"Last Modified: {file_info['last_modified']}")


def transform_string(input_string: str) -> str:
    # Remove forbidden characters for Windows and macOS filenames
    forbidden_chars = ['\\', ':', '*', '?', '"', '<', '>', '|', '\0', '-', ',']
    
    # First remove forbidden characters
    cleaned_string = input_string
    for char in forbidden_chars:
        cleaned_string = cleaned_string.replace(char, '')
    
    # Replace consecutive spaces with single underscore
    cleaned_string = ' '.join(cleaned_string.split())
    # Replace spaces with underscores
    no_spaces = cleaned_string.replace(' ', '_')
    # Convert to lowercase
    result = no_spaces.casefold()
    return result



# -------------------------- EXTRACT THE INFORMATION FROM GOOGLE DRIVE FILES --------------

def extract_image_urls_from_html(html_content):
    """Extract image URLs from HTML content."""
    # This is a simple extraction and might need to be more robust
    import re
    image_urls = re.findall(r'<img.*?src="(.*?)"', html_content)
    return [{"url": url} for url in image_urls]

def read_file_content(service, file_id, mime_type):
    """Read the content of a file based on its MIME type and extract images if possible."""
    try:
        content = ""
        images = []

        if 'vnd.google-apps.document' in mime_type:
            # Google Docs
            doc = service.files().export(fileId=file_id, mimeType='text/html').execute()
            content = doc.decode('utf-8')
            # Extract image URLs from the HTML content
            images = extract_image_urls_from_html(content)
        elif 'vnd.google-apps.spreadsheet' in mime_type:
            # Google Sheets
            sheet = service.files().export(fileId=file_id, mimeType='text/csv').execute()
            content = sheet.decode('utf-8')
        elif 'pdf' in mime_type:
            # PDF - we can't easily extract text or images without additional libraries
            content = "PDF content (not extracted)"
        elif 'image/' in mime_type:
            # Image file
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            image_data = base64.b64encode(fh.getvalue()).decode('utf-8')
            images.append({"name": f"image_{file_id}", "data": image_data})
            content = "Image file"
        else:
            content = "Content not readable"

        return content, images
    except Exception as e:
        return f"Error reading file: {str(e)}", []


# --------------- RUN GOOGLE DRIVE API --------------------------------------

# def main():
#     # Initialize the client
#     creds_path = "penelope-database-assistant/penelope/credentials.json"
#     service = init_drive_client(creds_path)
    
#     file_paths = None
#     # If the client was successfully initialized, retrieve the files
#     if service:
#         folder_names = ['database assistant']
#         folders_and_files = get_folders_and_files(service, folder_names=folder_names)
#         if folders_and_files:
#             file_paths = folders_and_files[1]
    
#     return file_paths


# main()


# ----------------------- TOOLS ----------------------------------------------------

# ---- COINGECKO -----

# Returns a list of Dicts with all the available coins in Coingecko
def get_list_of_coins():
    try:
        coingecko_response = requests.get(f'{COINGECKO_BASE_URL}/coins/list', headers=coingecko_headers)
        if coingecko_response.status_code == 200:
            return coingecko_response.json()
        
        return None
    except Exception as e:
        return None

def find_best_match_ids(param, coins):
    def similarity(a, b):
        return SequenceMatcher(None, a, b).ratio()

    matches = []
    highest_similarity = 0.0

    for coin in coins:
        name_similarity = similarity(param.lower(), coin["name"].lower())
        symbol_similarity = similarity(param.lower(), coin["symbol"].lower())
        id_similarity = similarity(param.lower(), coin["id"].lower())

        # if coin['id'] == 'solana':
        #     print("name_similarity: ", name_similarity)
        #     print("symbol_similarity: ", symbol_similarity)
        #     print("id_similarity: ", id_similarity)

        if name_similarity >= highest_similarity or symbol_similarity >= highest_similarity or id_similarity >= highest_similarity:
            highest_similarity = max(name_similarity, symbol_similarity, id_similarity)
            matches.append(coin["id"])

    return matches

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
        coins = get_list_of_coins()

        # Calculate the date one year ago
        one_year_ago = current_date - timedelta(days=365)
        formatted_date = one_year_ago.strftime('%d-%m-%Y')

        formatted_coin = str(coin).casefold().strip()
        coins_list = find_best_match_ids(param=formatted_coin, coins=coins)

        coins_data_list = []
      
        for coin in coins_list:
            response = requests.get(f'{COINGECKO_BASE_URL}/coins/{coin}', headers=coingecko_headers)
            historical_response = requests.get(f'{COINGECKO_BASE_URL}/coins/{coin}/history?date={formatted_date}', headers=coingecko_headers)

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

                coin_data =  {
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
                if market_cap_usd > 100000:
                    coins_data_list.append(coin_data)
       
        return coins_data_list
    except Exception as e:
        print(f'Coingecko error: {str(e)}')
        return None


# ---- NEWS --------

def find_best_match_symbols(param, coins):
    def similarity(a, b):
        return SequenceMatcher(None, a, b).ratio()

    matches = []
    highest_similarity = 0.0

    for coin in coins:
        name_similarity = similarity(param.lower(), coin["name"].lower())
        symbol_similarity = similarity(param.lower(), coin["symbol"].lower())
        id_similarity = similarity(param.lower(), coin["id"].lower())

        # if coin['id'] == 'solana':
        #     print("name_similarity: ", name_similarity)
        #     print("symbol_similarity: ", symbol_similarity)
        #     print("id_similarity: ", id_similarity)

        if name_similarity >= highest_similarity or symbol_similarity >= highest_similarity or id_similarity >= highest_similarity:
            highest_similarity = max(name_similarity, symbol_similarity, id_similarity)
            matches.append(coin["symbol"])

    return matches

def find_ids_by_name(data, name):
    matching_ids = []
    for item in data["data"]:
        if item["name"].lower() == name.lower():
            matching_ids.append(item["id"])
    return matching_ids if matching_ids else None

def get_bots():
    url = "https://zztc5v98-5001.uks1.devtunnels.ms/bots"
    headers = {
        "accept": "application/json"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Will raise an HTTPError for bad responses (4xx and 5xx)
        return response.json()  # Assuming the response is in JSON format
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None

def get_latest_news(coin):
    """
    Retrieves articles related to the specified token from a given API endpoint and returns the content of each article.

    Parameters:
    token_name (str): The name of the token for which to retrieve articles.

    Returns:
    list of dict: A list containing dictionaries with 'news' and 'date' keys for each article retrieved from the API.
                 Returns None if no articles are found or if there's an error.
    """
    
    # Get all available tokens on CoinGecko
    coins = get_list_of_coins()
    
    # Find best match symbols for the token name
    symbols = find_best_match_symbols(param=coin, coins=coins)
    
    # Get all available bots
    all_bots = get_bots()
    
    # Initialize an empty list to store news articles
    news_list = []
    
    # Set a limit for the number of articles to retrieve
    limit = 10
    
    # Iterate over each symbol found
    for symbol in symbols:
        # Find bot IDs corresponding to the symbol
        bot_ids = find_ids_by_name(all_bots, symbol)
        
        # If no bot IDs found, continue to next symbol
        if not bot_ids:
            continue
        
        # Iterate over each bot ID
        for bot_id in bot_ids:
            if not bot_id:
                continue
            
            # Construct the URL for the API request
            url = f"https://zztc5v98-5001.uks1.devtunnels.ms/get_articles?bot_id={bot_id}&limit={limit}"
            
            try:
                # Make the API request
                response = requests.get(url)
                
                # Check if the request was successful
                if response.status_code == 200:
                    data = response.json().get('data', [])
                    
                    # Extract relevant data from each article
                    for article in data:
                        news_list.append({'news': article['content'], 'date': article['date']})
                
                # If the request was not successful, log the status code
                else:
                    print(f"Failed to fetch articles. Status code: {response.status_code}")
            
            # Handle exceptions that might occur during the request
            except requests.exceptions.RequestException as e:
                # print(f"Error fetching articles: {e}")
                continue
    
    # Return the list of news articles, or None if no articles were found
    return news_list if news_list else None


# ----------------------------- ASSISTANT ------------------------

assistant_name = 'penelope'
model = 'gpt-4o'
system_instructions = "You are Penelope, an exceptionally polite and intelligent AI Assistant. You specialize in creating detailed analyses, writing concise summaries, conducting thorough information searches, and retrieving real-time data efficiently."
tools=[ {"type": "code_interpreter"}, 
        {"type": "file_search"},
        {
            "type": "function",
            "function": {
                "name": "get_latest_news",
                "description": "Retrieves the latest news related to the specified token from a given API endpoint and returns the content of each article",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "coin": {
                            "type": "string",
                            "description": "name of the token, e.g. solana",
                        },
                    },
                    "required": ["coin"],
                    },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_token_data",
                "description": "Fetch detailed data about a cryptocurrency token from the CoinGecko API",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "coin": {
                            "type": "string",
                            "description": "name of the coin, e.g. solana",
                        },
                    },
                    "required": ["coin"],
                    },
            },
        },
       
    ]

def list_assistants():
    """
    Retrieves a list of all existing assistants.

    This function fetches all existing assistants and returns a list of dictionaries,
    each containing the name and ID of an assistant.

    Returns:
        list: A list of dictionaries with the name and ID of each assistant.
              Example: [{'name': 'AssistantName1', 'id': 'assistant_id_1'}, ...]
    """
    response = {'assistants': [], 'success': False}

    try:
        # Retrieve the list of existing assistants
        existing_assistants = client.beta.assistants.list()

        # Create a list of dictionaries with name and ID
        assistants_list = [{'name': assistant.name, 'id': assistant.id} for assistant in existing_assistants]
        
        response['assistants'] = assistants_list
        response['success'] = True

    except Exception as e:
        response['assistants'] = []
        response['success'] = False
        response['error'] = f'An unexpected error occurred: {str(e)}'

    return response

# Example usage
# print(list_assistants())


def delete_assistant(assistant_id):
    """
    Deletes an assistant by its ID.

    This function attempts to delete an assistant identified by the provided `assistant_id`.
    If the deletion is successful, it returns a response indicating success.
    If the deletion fails or an error occurs, it returns a response with the appropriate error message.

    Args:
        assistant_id (str): The ID of the assistant to be deleted.

    Returns:
        dict: A dictionary containing the response message and a success flag.
              Example: {'response': 'Assistant deleted successfully', 'success': True}
    """
    response = {'response': None, 'success': False}
    try:
        del_response = client.beta.assistants.delete(assistant_id=assistant_id)
        if del_response.deleted:
            response['response'] = 'Assistant deleted successfully'
            response['success'] = True
        else:
            response['response'] = 'Failed to delete the assistant. No deletion confirmation received.'

    except Exception as e:
        response['response'] = f'An unexpected error occurred: {str(e)}'
    return response


# Example usage
# print(delete_assistant('asst_VzRa8bVNpvA0BjfSbmtFYJiW'))

def create_or_update_assistant(name, instructions, model, tools, vector_store_id):
    """
    Creates a new assistant or deletes an existing one if a similar assistant already exists
    and creates a new one.

    Args:
        name (str): The name of the assistant.
        instructions (str): The instructions for the assistant.
        model (str): The model to use for the assistant.
        tools (list): A list of tools to be used by the assistant.

    Returns:
        dict: A dictionary containing the response message and a success flag.
              Example: {'response': 'Created new assistant: AssistantName', 'success': True}
    """
    response = {'response': None, 'success': False}

    try:
        # Search for existing assistants with the same name
        existing_assistants = client.beta.assistants.list()

        for existing_assistant in existing_assistants:
            if existing_assistant.name.lower() == name.lower():
                # Delete the existing assistant
                delete_response = delete_assistant(existing_assistant.id)
                if not delete_response['success']:
                    response['response'] = f"Failed to delete the existing assistant: {delete_response['response']}"
                    response['success'] = False
                    return response

                # Create a new assistant
                assistant = client.beta.assistants.create(
                    name=name,
                    instructions=instructions,
                    model=model,
                    tools=tools,
                    tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}}
                )
                response['response'] = f"Deleted old version and created new assistant: {assistant.name}"
                response['success'] = True
                return response

        # If no similar assistant exists, create a new one
        assistant = client.beta.assistants.create(
            name=name,
            instructions=instructions,
            model=model,
            tools=tools,
            tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}}

        )
        response['response'] = f"Created new assistant: {assistant.name}"
        response['success'] = True

    except Exception as e:
        response['response'] = f'An unexpected error occurred: {str(e)}'
    
    return response


# Example usage
# print(create_or_update_assistant(name=assistant_name,
#                            instructions=system_instructions,
#                            model=model,
#                            tools=tools,
#                            vector_store_id='vs_JrnFQpY13BFw5sNjBKnRqTWF'
#                            ))

def list_documents(root_folder, extensions=None):
    """
    Recursively lists absolute paths to documents (files) within a root folder, filtered by extensions.

    Args:
    - root_folder (str): The root folder to start the search from.
    - extensions (list): List of file extensions to filter. Example: ['.pdf', '.txt']

    Returns:
    - file_paths (list): List of absolute paths to documents found matching the extensions.
    """
    file_paths = []

    for root, _, files in os.walk(root_folder):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            if extensions:
                # Check if the file has one of the specified extensions
                _, file_ext = os.path.splitext(file_name)
                if file_ext.lower() in extensions:
                    file_paths.append(file_path)
            else:
                # If no extensions are specified, add all files
                file_paths.append(file_path)

    return file_paths

# Example usage:
# root_folder = 'penelope-database-assistant/downloads'
# extensions = ['.pdf', '.txt'] 
# file_paths = list_documents(root_folder, extensions=extensions)
# print('Documents:', len(file_paths))


def create_vector_store(name, file_paths):
    try:
        if not name or not file_paths:
            return None
        
        # Check if the vector store already exists
        existing_stores = client.beta.vector_stores.list()
        existing_store = next((store for store in existing_stores if store.name.lower() == name.lower()), None)
        
        if existing_store:
            vector_store = existing_store
            print(f'Using existing vector store: {vector_store.name}')
        else:
            vector_store = client.beta.vector_stores.create(name=name)
            print(f'Created new vector store: {vector_store.name}')
        
        # Split file_paths into batches of 10 files each
        batch_size = 200
        for i in range(0, len(file_paths), batch_size):
            batch_paths = file_paths[i:i + batch_size]
            file_streams = []
            
            try:
                for path in batch_paths:
                    file_name = os.path.basename(path)
                    if file_name:
                        file_streams.append(open(path, "rb"))
                    else:
                        print(f"File {file_name} already exists in the vector store. Skipping.")
                
                if file_streams:
                    # Use the upload and poll SDK helper to upload the files, add them to the vector store,
                    # and poll the status of the file batch for completion.
                    file_batch = client.beta.vector_stores.file_batches.upload_and_poll(
                        vector_store_id=vector_store.id, files=file_streams
                    )

                    print(f"Batch {i // batch_size + 1} status: {file_batch.status}")
                    print(f"Batch {i // batch_size + 1} file counts: {file_batch.file_counts}")
                else:
                    print(f"Batch {i // batch_size + 1}: No new files to upload.")
            
            finally:
                # Ensure all files are closed
                for file in file_streams:
                    file.close()
        
        return vector_store.id
        
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

# Example usage
# print('res: ', create_vector_store(name='protocols', file_paths=file_paths[:100]))


def penelope(prompt: str, assistant_id: str = 'asst_jwh3njdJyaD745IC2SXkCbO5', max_retries: int = 10, delay: float = 2):
    """
    Interact with an AI assistant to process a given prompt.

    Args:
        prompt (str): The user's input prompt.
        assistant_id (str): The ID of the AI assistant to use.
        max_retries (int): Maximum number of retries for failed attempts.
        delay (float): Delay between retries in seconds.

    Returns:
        Dict[str, Any]: A dictionary containing the response and success status.
    """
    response = {'response': None, 'success': False}
    
    for attempt in range(max_retries):
        try:
            assistant = client.beta.assistants.retrieve(assistant_id=assistant_id)
            thread = client.beta.threads.create(messages=[{"role": "user", "content": prompt}])
            
            run = client.beta.threads.runs.create_and_poll(
                thread_id=thread.id,
                assistant_id=assistant.id
            )

            if run.status == 'completed':
                return _process_completed_run(thread.id, response)
            
            if run.status in ["failed", "cancelled", "expired"]:
                raise Exception(f"Run failed with status: {run.status}")
            
             # Check if tool outputs are required
            if hasattr(run, 'required_action') and hasattr(run.required_action, 'submit_tool_outputs'):
                tool_outputs = _process_tool_calls(run.required_action.submit_tool_outputs.tool_calls)

                if tool_outputs:
                    second_run = client.beta.threads.runs.submit_tool_outputs_and_poll(
                        thread_id=thread.id,
                        run_id=run.id,
                        tool_outputs=tool_outputs
                    )
                    print("Tool outputs submitted successfully.", tool_outputs)

                    if second_run.status == 'completed':
                        return _process_completed_run(thread.id, response)
                    else:
                        print(f"Run status after tool submission: {run.status}")
                else:
                    print("No tool outputs to submit.")
            else:
                print("No tool calls required or `submit_tool_outputs` not found.")

        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                response['response'] = f"All attempts failed. Last error: {str(e)}"
                return response

    return response

def _process_completed_run(thread_id, response):
    """Process a completed run and update the response dictionary."""
    messages = client.beta.threads.messages.list(thread_id=thread_id)
    assistant_message = messages.data[0].content[0].text.value
    response['response'] = assistant_message
    response['success'] = True
    return response

def _process_tool_calls(tool_calls: list) -> list:
    """Process tool calls and return a list of tool outputs."""
    tool_outputs = []
    for tool in tool_calls:
        if tool.function.name in ["get_token_data", "get_latest_news"]:
            args = json.loads(tool.function.arguments)
            arg_value = args.get('coin')

            output = None
            if tool.function.name == 'get_token_data':
                output = get_token_data(arg_value)

            if tool.function.name == 'get_latest_news':
                output = get_latest_news(arg_value)

            tool_outputs.append({
                "tool_call_id": tool.id,
                "output": str(output)
            })
    return tool_outputs




class Penelope:
    def __init__(self, name, instructions, model, tools, api_key):
        self.name = name
        self.instructions = instructions
        self.model = model
        self.tools = tools
        self.extensions = ['.pdf', '.txt']
        self.root_folder = 'download'
        self.file_paths = self.list_documents(self.root_folder, self.extensions)

        if api_key:
            # Initialize OpenAI client
            self.client = OpenAI(api_key=api_key)
        else:
            raise ValueError("API key must be provided")

        # Create a vector store
        vector_store_response = self.create_vector_store()
        if not vector_store_response['success']:
            raise Exception(f"Failed to create vector store: {vector_store_response['message']}")

        self.vector_store_id = vector_store_response['vector_store_id']

        # Create an assistant
        assistant_response = self.create_assistant(
            name=f"{self.name}_assistant",
            instructions=self.instructions,
            model=self.model,
            tools=["tool1", "tool2"],
            vector_store_id=self.vector_store_id
        )
        if not assistant_response['success']:
            raise Exception(f"Failed to create assistant: {assistant_response['response']}")
        
        self.assistant = assistant_response['assistant']

    @staticmethod
    def list_documents(root_folder, extensions=None):
        """
        Recursively lists absolute paths to documents (files) within a root folder, filtered by extensions.

        Args:
        - root_folder (str): The root folder to start the search from.
        - extensions (list): List of file extensions to filter. Example: ['.pdf', '.txt']

        Returns:
        - file_paths (list): List of absolute paths to documents found matching the extensions.
        """
        file_paths = []

        for root, _, files in os.walk(root_folder):
            for file_name in files:
                file_path = os.path.join(root, file_name)
                if extensions:
                    # Check if the file has one of the specified extensions
                    _, file_ext = os.path.splitext(file_name)
                    if file_ext.lower() in extensions:
                        file_paths.append(file_path)
                else:
                    # If no extensions are specified, add all files
                    file_paths.append(file_path)

        return file_paths

    def list_assistants(self):
        """
        Retrieves a list of all existing assistants.

        This function fetches all existing assistants and returns a list of dictionaries,
        each containing the name and ID of an assistant.

        Returns:
            dict: A dictionary containing the assistants list and a success flag.
                  Example: {'assistants': [{'name': 'AssistantName1', 'id': 'assistant_id_1'}, ...], 'success': True}
        """
        response = {'assistants': [], 'success': False}

        try:
            # Retrieve the list of existing assistants
            existing_assistants = self.client.beta.assistants.list()

            # Create a list of dictionaries with name and ID
            assistants_list = [{'name': assistant.name, 'id': assistant.id} for assistant in existing_assistants]
            
            response['assistants'] = assistants_list
            response['success'] = True

        except Exception as e:
            response['assistants'] = []
            response['success'] = False
            response['error'] = f'An unexpected error occurred: {str(e)}'

        return response

    def delete_assistant(self, assistant_id):
        """
        Deletes an assistant by its ID.

        This function attempts to delete an assistant identified by the provided `assistant_id`.
        If the deletion is successful, it returns a response indicating success.
        If the deletion fails or an error occurs, it returns a response with the appropriate error message.

        Args:
            assistant_id (str): The ID of the assistant to be deleted.

        Returns:
            dict: A dictionary containing the response message and a success flag.
                  Example: {'response': 'Assistant deleted successfully', 'success': True}
        """
        response = {'response': None, 'success': False}
        try:
            del_response = self.client.beta.assistants.delete(assistant_id=assistant_id)
            if del_response.deleted:
                response['response'] = 'Assistant deleted successfully'
                response['success'] = True
            else:
                response['response'] = 'Failed to delete the assistant. No deletion confirmation received.'

        except Exception as e:
            response['response'] = f'An unexpected error occurred: {str(e)}'
        
        return response

    def create_vector_store(self, name, file_paths):
        response = {'vector_store_id': None, 'success': False, 'message': None}
        try:
            if not name or not file_paths:
                response['message'] = 'Name or file paths are missing.'
                return response
            
            # Check if the vector store already exists
            existing_stores = self.client.beta.vector_stores.list()
            existing_store = next((store for store in existing_stores if store.name.lower() == name.lower()), None)
            
            if existing_store:
                vector_store = existing_store
                response['message'] = f'Using existing vector store: {vector_store.name}'
            else:
                vector_store = self.client.beta.vector_stores.create(name=name)
                response['message'] = f'Created new vector store: {vector_store.name}'
            
            # Split file_paths into batches of 200 files each
            batch_size = 200
            for i in range(0, len(file_paths), batch_size):
                batch_paths = file_paths[i:i + batch_size]
                file_streams = []
                
                try:
                    for path in batch_paths:
                        file_name = os.path.basename(path)
                        if file_name:
                            file_streams.append(open(path, "rb"))
                        else:
                            response['message'] = f"File {file_name} already exists in the vector store. Skipping."
                    
                    if file_streams:
                        # Use the upload and poll SDK helper to upload the files, add them to the vector store,
                        # and poll the status of the file batch for completion.
                        file_batch = self.client.beta.vector_stores.file_batches.upload_and_poll(
                            vector_store_id=vector_store.id, files=file_streams
                        )

                        response['message'] = f"Batch {i // batch_size + 1} status: {file_batch.status}"
                        response['message'] += f"Batch {i // batch_size + 1} file counts: {file_batch.file_counts}"
                    else:
                        response['message'] = f"Batch {i // batch_size + 1}: No new files to upload."
                
                finally:
                    # Ensure all files are closed
                    for file in file_streams:
                        file.close()
            
            response['vector_store_id'] = vector_store.id
            response['success'] = True
            
        except Exception as e:
            response['message'] = f"An error occurred: {str(e)}"
        
        return response

    def create_assistant(self, name, instructions, model, tools, vector_store_id):
        """
        Creates a new assistant.

        Args:
            name (str): The name of the assistant.
            instructions (str): The instructions for the assistant.
            model (str): The model to use for the assistant.
            tools (list): A list of tools to be used by the assistant.

        Returns:
            dict: A dictionary containing the response message, assistant object and a success flag.
                  Example: {'response': 'Created new assistant: AssistantName', 'success': True, 'assistant': assistant}
        """
        response = {'response': None, 'success': False, 'assistant': None}

        try:
            assistans = self.list_assistants()
            for assistant in assistans:
                if assistant.name.lower() == name.lower():
                    response['response'] = 'Assitant already exist. Uusing existant assistant'
                    response['assistant'] = assistant
                    response['success'] = True
                    break

            new_assistant = self.client.beta.assistants.create(
                name=name,
                instructions=instructions,
                model=model,
                tools=tools,
                tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}}
            )
            response['response'] = f"Created new assistant: {new_assistant.name}"
            response['assistant'] = new_assistant
            response['success'] = True

        except Exception as e:
            response['response'] = f'An unexpected error occurred: {str(e)}'
        
        return response

    def update_assistant(self, existing_assistant_id, instructions, model, tools, temperature, vector_store_id):
        """
        Updates the configuration of an existing assistant.

        This method updates an assistant identified by the provided `existing_assistant_id` with new settings,
        including instructions, model, tools, temperature, and vector store IDs. If the update is successful, 
        it returns a dictionary containing a success flag, a response message, and the updated assistant object.

        Args:
            existing_assistant_id (str): The ID of the assistant to be updated.
            instructions (str): The new instructions for the assistant.
            model (str): The new model to use for the assistant.
            tools (list): A list of tools to be used by the assistant.
            temperature (float): The temperature setting for the assistant (controls randomness).
            vector_store_id (str): The ID of the vector store to be used by the assistant.

        Returns:
            dict: A dictionary containing the response message, assistant object, and a success flag.
                Example: {'response': 'Updated assistant: AssistantName', 'success': True, 'assistant': assistant}
        """
        response = {'response': None, 'success': False, 'assistant': None}

        try:
            update_response = self.client.beta.assistants.update(
                assistant_id=existing_assistant_id,
                instructions=instructions,
                model=model,
                tools=tools,
                temperature=temperature,
                tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
            )
            response['response'] = f"Updated assistant: {update_response.name} successfully"
            response['assistant'] = update_response
            response['success'] = True
        except Exception as e:
            response['response'] = f'Error updating assistant: {str(e)}'
        
        return response

# Example usage
assistant_name = 'penelope'
model = 'gpt-4o'
system_instructions = "You are Penelope, an exceptionally polite and intelligent AI Assistant. You specialize in creating detailed analyses, writing concise summaries, conducting thorough information searches, and retrieving real-time data efficiently."
tools=[ {"type": "code_interpreter"}, 
        {"type": "file_search"},
        {
            "type": "function",
            "function": {
                "name": "get_latest_news",
                "description": "Retrieves the latest news related to the specified token from a given API endpoint and returns the content of each article",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "coin": {
                            "type": "string",
                            "description": "name of the token, e.g. solana",
                        },
                    },
                    "required": ["coin"],
                    },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_token_data",
                "description": "Fetch detailed data about a cryptocurrency token from the CoinGecko API",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "coin": {
                            "type": "string",
                            "description": "name of the coin, e.g. solana",
                        },
                    },
                    "required": ["coin"],
                    },
            },
        },
       
    ]


new_assistant = Penelope(name=assistant_name,
                         instructions=system_instructions,
                         model=model,
                         tools=tools,
                         api_key=OPENAI_KEY
                         )

print('new_assistant.name: ', new_assistant.name)

# app = Flask(__name__)
# CORS(app)

# @app.route('/process', methods=['POST'])
# def process():
#     try:
#         user_input = request.get_json()
#         response = {'response': None, 'success': None}
        
#         if not user_input or not user_input.get('input'):
#             raise ValueError("No input data provided")
        
#         # def generate():
#         #     for chunk in ask_penelope_stream(user_input.get('input')):
#         #         yield f"{chunk}"
#         # return Response(generate(), content_type='application/jsonlines')

#         # output = ask_penelope_stream(user_input.get('input'))

#         output = penelope(prompt=user_input.get('input'))
#         if output['success']:
#             response['response'] = output['response']
#             response['success'] = True
#             return response
#         else:
#             response['response'] = output['response']
#             return response
        
#     except ValueError as ve:
#         response['response'] = f"ValueError: {str(ve)}"
#         return response
    
#     except Exception as e:
#         response['response'] = f"Exception: {str(e)}"
#         return response


# @app.route('/')
# def home():
#     return "Penelope API is running"

# if __name__ == "__main__":
#     app.run(host='0.0.0.0', port=5000, use_reloader=True)






