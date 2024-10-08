import ast
import os

from dotenv import load_dotenv

from utils.Logger import logger

load_dotenv(encoding="ascii")


def is_true(x):
    if isinstance(x, bool):
        return x
    if isinstance(x, str):
        return x.lower() in ['true', '1', 't', 'y', 'yes']
    elif isinstance(x, int):
        return x == 1
    else:
        return False


api_prefix = os.getenv('API_PREFIX', None)
authorization = os.getenv('AUTHORIZATION', '').replace(' ', '')
chatgpt_base_url = os.getenv('CHATGPT_BASE_URL', 'https://chatgpt.com').replace(' ', '')
auth_key = os.getenv('AUTH_KEY', None)
user_agents = os.getenv('USER_AGENTS', '[]')

ark0se_token_url = os.getenv('ARK' + 'OSE_TOKEN_URL', '').replace(' ', '')
if not ark0se_token_url:
    ark0se_token_url = os.getenv('ARK0SE_TOKEN_URL', None)
proxy_url = os.getenv('PROXY_URL', '').replace(' ', '')
export_proxy_url = os.getenv('EXPORT_PROXY_URL', None)
cf_file_url = os.getenv('CF_FILE_URL', None)

history_disabled = is_true(os.getenv('HISTORY_DISABLED', True))
pow_difficulty = os.getenv('POW_DIFFICULTY', '000032')
retry_times = int(os.getenv('RETRY_TIMES', 3))
enable_gateway = is_true(os.getenv('ENABLE_GATEWAY', True))
conversation_only = is_true(os.getenv('CONVERSATION_ONLY', False))
enable_limit = is_true(os.getenv('ENABLE_LIMIT', True))
limit_status_code = os.getenv('LIMIT_STATUS_CODE', 429)
refresh_server = os.getenv('REFRESH_SERVER', 'oaifree')
check_model = is_true(os.getenv('CHECK_MODEL', False))
scheduled_refresh = is_true(os.getenv('SCHEDULED_REFRESH', True))

enable_search = is_true(os.getenv('ENABLE_SEARCH', False))
max_file_num = int(os.getenv('MAX_FILE_NUM', 5))
enable_gpt4o_search = is_true(os.getenv('ENABLE_GPT4O_SEARCH', False))
enable_search_prefix = os.getenv('ENABLE_SEARCH_PREFIX', 'http')
enable_system_prompt = is_true(os.getenv('ENABLE_SYSTEM_PROMPT', False))
system_prompt = os.getenv('SYSTEM_PROMPT', 'You are ChatGPT, a large language model trained by OpenAI.'
                                           'Current model: {model}'
                                           'Current time: {time}'
                                           'Latex inline: \\(x^2\\) '
                                           'Latex block: $$e=mc^2$$'
                                           'Please do not answer questions about pornography, violence')
authorization_list = authorization.split(',') if authorization else []
chatgpt_base_url_list = chatgpt_base_url.split(',') if chatgpt_base_url else []
ark0se_token_url_list = ark0se_token_url.split(',') if ark0se_token_url else []
proxy_url_list = proxy_url.split(',') if proxy_url else []
user_agents_list = ast.literal_eval(user_agents)

logger.info("-" * 60)
logger.info("Chat2Api v1.4.7 | https://github.com/lanqian528/chat2api")
logger.info("-" * 60)
logger.info("Environment variables:")
logger.info("API_PREFIX:            " + str(api_prefix))
logger.info("AUTHORIZATION:         " + str(authorization_list))
logger.info("CHATGPT_BASE_URL:      " + str(chatgpt_base_url_list))
logger.info("AUTH_KEY:              " + str(auth_key))
logger.info("ARKOSE_TOKEN_URL:      " + str(ark0se_token_url_list))
logger.info("PROXY_URL:             " + str(proxy_url_list))
logger.info("EXPORT_PROXY_URL:      " + str(export_proxy_url))
logger.info("HISTORY_DISABLED:      " + str(history_disabled))
logger.info("POW_DIFFICULTY:        " + str(pow_difficulty))
logger.info("RETRY_TIMES:           " + str(retry_times))
logger.info("ENABLE_GATEWAY:        " + str(enable_gateway))
logger.info("CONVERSATION_ONLY:     " + str(conversation_only))
logger.info("ENABLE_LIMIT:          " + str(enable_limit))
logger.info("LIMIT_STATUS_CODE      " + str(limit_status_code))
logger.info("RFRESH_SERVER:         " + str(refresh_server))
logger.info("ENABLE_SEARCH:         " + str(enable_search))
logger.info("MAX_FILE_NUM:          " + str(max_file_num))
logger.info("ENABLE_GPT4O_SEARCH:   " + str(enable_gpt4o_search))
logger.info("ENABLE_SEARCH_PREFIX:  " + str(enable_search_prefix))
logger.info("CHECK_MODEL:           " + str(check_model))
logger.info("SCHEDULED_REFRESH:     " + str(scheduled_refresh))
logger.info("ENABLE_SYSTEM_PROMPT:  " + str(enable_system_prompt))
logger.info("USER_AGENTS:       " + str(user_agents_list))
if system_prompt:
    logger.info("SYSTEM_PROMPT:         " + str(system_prompt))
logger.info("-" * 60)
