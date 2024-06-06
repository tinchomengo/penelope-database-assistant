from abacusai import ApiClient
import dotenv
import os

# Load environment variables from a .env file
dotenv.load_dotenv()

ABACUS_API_KEY = os.getenv('ABACUS_API_KEY')
ABACUS_MODEL_TOKEN = os.getenv('ABACUS_MODEL_TOKEN')

# Initialize the API client
client = ApiClient(api_key=ABACUS_API_KEY)

def list_abacus_projects():
    """
    List all projects available in Abacus.AI
    """
    try:
        projects = client.list_projects()
        projects_data = []

        for project in projects:
            project_models = client.list_models(project.project_id)
            models_data = []

            for model in project_models:
                model_data = {
                    'model_name': model.name,
                    'model_id': model.model_id,
                    'model_created_at': model.created_at,
                    'latest_model_status': model.latest_model_version.status,
                }
                models_data.append(model_data)

            project_info = {
                'project_id': project.project_id,
                'project_name': project.name,
                'project_created_at': project.created_at,
                'models': models_data
            }
            projects_data.append(project_info)

        return {'data': projects_data, 'error': None, 'success': True}
    except Exception as e:
        return {'data': None, 'error': str(e), 'success': False}


def ask_abacus_model(prompt):
    """
    Send a query/prompt to an Abacus.AI model for inference.

    Parameters:
    prompt (str): The query/prompt to send to the model.
    """
    try:
        response = client.get_chat_response(
            deployment_id='1209bcfb2c', 
            deployment_token=ABACUS_MODEL_TOKEN,
            messages=[{"is_user": True, "text": prompt}]
        )
        
        data = {}
        base_result = response['messages'][1]['text']

        result_text = f'{base_result}\n\n'

        search_results = response['search_results']
        for result in search_results:
            data_result = result['results']
            for data_item in data_result:
                answer = data_item['answer']
                result_text = result_text + answer

        data['text_response'] = result_text
        
        return {'data': data, 'error': None, 'success': True}
    except Exception as e:
        return {'data': None, 'error': str(e), 'success': False}


# print(ask_abacus_model(prompt='what is the current market cap of eth'))
