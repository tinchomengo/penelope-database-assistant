from datetime import timedelta, datetime
from dotenv import load_dotenv
import requests
import os

# Load environment variables from the .env file
load_dotenv()
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

BASE_URL = 'https://pro-api.coingecko.com/api/v3'

headers = {
            "Content-Type": "application/json",
            "x-cg-pro-api-key": COINGECKO_API_KEY,
        }


# Get basic data from Coingecko
def get_token_data(coin):
    try:
        # Get today's date
        current_date = datetime.now()

        # Calculate the date one year ago
        one_year_ago = current_date - timedelta(days=365)
        formatted_date = one_year_ago.strftime('%d-%m-%Y')

        formatted_coin = str(coin).casefold().strip()
        response = requests.get(f'{BASE_URL}/coins/{formatted_coin}', headers=headers)
        historical_response = requests.get(f'{BASE_URL}/coins/{formatted_coin}/history?date={formatted_date}', headers=headers)
      
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
            return {'response': response.content.decode('utf-8'), 'success': False}
    except Exception as e:
        return {'response': str(e), 'success': False}
    

print(get_token_data('bitcoin'))