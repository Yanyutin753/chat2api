import asyncio
import json
import random
import re
import string
import time
import uuid
from collections import deque
from functools import reduce

import pybase64
import websockets
from fastapi import HTTPException
from urlextract import URLExtract

from api.files import get_file_content
from api.models import model_system_fingerprint
from api.tokens import split_tokens_from_content, calculate_image_tokens, num_tokens_from_messages
from utils.Logger import logger
from utils.config import max_file_num, enable_search, enable_gpt4o_search, enable_search_prefix, enable_system_prompt, \
    system_prompt

moderation_message = ("I'm sorry, I cannot provide or engage in any content related to pornography, violence, "
                      "or any unethical material. If you have any other questions or need assistance, please feel "
                      "free to let me know. I'll do my best to provide support and assistance.")


async def format_not_stream_response(response, prompt_tokens, max_tokens, model):
    chat_id = f"chatcmpl-{''.join(random.choice(string.ascii_letters + string.digits) for _ in range(29))}"
    system_fingerprint_list = model_system_fingerprint.get(model, None)
    system_fingerprint = random.choice(system_fingerprint_list) if system_fingerprint_list else None
    created_time = int(time.time())
    all_text = ""
    async for chunk in response:
        try:
            if chunk.startswith("data: [DONE]"):
                break
            elif not chunk.startswith("data: "):
                continue
            else:
                chunk = json.loads(chunk[6:])
                if not chunk["choices"][0].get("delta"):
                    continue
                all_text += chunk["choices"][0]["delta"]["content"]
        except Exception as e:
            logger.error(f"Error: {chunk}, error: {str(e)}")
            continue
    content, completion_tokens, finish_reason = await split_tokens_from_content(all_text, max_tokens, model)
    message = {
        "role": "assistant",
        "content": content,
    }
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens
    }
    if not message.get("content"):
        raise HTTPException(status_code=403, detail="No content in the message.")

    data = {
        "id": chat_id,
        "object": "chat.completion",
        "created": created_time,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "logprobs": None,
                "finish_reason": finish_reason
            }
        ],
        "usage": usage
    }
    if system_fingerprint:
        data["system_fingerprint"] = system_fingerprint
    return data


async def wss_stream_response(websocket, conversation_id):
    while not websocket.closed:
        try:
            message = await asyncio.wait_for(websocket.recv(), timeout=10)
            if message:
                resultObj = json.loads(message)
                sequenceId = resultObj.get("sequenceId", None)
                if not sequenceId:
                    continue
                data = resultObj.get("data", {})
                if conversation_id != data.get("conversation_id", ""):
                    continue
                sequenceId = resultObj.get('sequenceId')
                if sequenceId and sequenceId % 80 == 0:
                    await websocket.send(
                        json.dumps(
                            {"type": "sequenceAck", "sequenceId": sequenceId}
                        )
                    )
                decoded_bytes = pybase64.b64decode(data.get("body", None))
                yield decoded_bytes
            else:
                print("No message received within the specified time.")
        except asyncio.TimeoutError:
            logger.error("Timeout! No message received within the specified time.")
            break
        except websockets.ConnectionClosed as e:
            if e.code == 1000:
                logger.error("WebSocket closed normally with code 1000 (OK)")
                yield b"data: [DONE]\n\n"
            else:
                logger.error(f"WebSocket closed with error code {e.code}")
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            continue


async def head_process_response(response):
    async for chunk in response:
        chunk = chunk.decode("utf-8")
        if chunk.startswith("data: {"):
            chunk_old_data = json.loads(chunk[6:])
            message = chunk_old_data.get("message", {})
            if not message and "error" in chunk_old_data:
                return response, False
            role = message.get('author', {}).get('role')
            if role == 'user' or role == 'system':
                continue

            status = message.get("status")
            if status == "in_progress":
                return response, True
    return response, False


async def stream_response(service, response, model, max_tokens):
    chat_id = f"chatcmpl-{''.join(random.choice(string.ascii_letters + string.digits) for _ in range(29))}"
    system_fingerprint_list = model_system_fingerprint.get(model, None)
    system_fingerprint = random.choice(system_fingerprint_list) if system_fingerprint_list else None
    created_time = int(time.time())
    completion_tokens = 0
    len_last_content = 0
    len_last_citation = 0
    last_message_id = None
    last_content_type = None
    last_recipient = None
    end = False

    chunk_new_data = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created_time,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": ""},
                "logprobs": None,
                "finish_reason": None
            }
        ]
    }
    if system_fingerprint:
        chunk_new_data["system_fingerprint"] = system_fingerprint
    yield f"data: {json.dumps(chunk_new_data)}\n\n"

    try:
        async for chunk in response:
            chunk = chunk.decode("utf-8")
            if end:
                yield "data: [DONE]\n\n"
                break
            try:
                if chunk.startswith("data: {"):
                    chunk_old_data = json.loads(chunk[6:])
                    finish_reason = None
                    message = chunk_old_data.get("message", {})
                    conversation_id = chunk_old_data.get("conversation_id")
                    role = message.get('author', {}).get('role')
                    if role == 'user' or role == 'system':
                        continue

                    status = message.get("status")
                    message_id = message.get("id")
                    content = message.get("content", {})
                    recipient = message.get("recipient", "")

                    if not message and chunk_old_data.get("type") == "moderation":
                        delta = {"role": "assistant", "content": moderation_message}
                        finish_reason = "stop"
                        end = True
                    elif status == "in_progress":
                        outer_content_type = content.get("content_type")
                        if outer_content_type == "text":
                            part = content.get("parts", [])[0]
                            if not part:
                                new_text = ""
                            else:
                                if last_message_id and last_message_id != message_id:
                                    continue
                                citation = message.get("metadata", {}).get("citations", [])
                                if len(citation) > len_last_citation:
                                    inside_metadata = citation[-1].get("metadata", {})
                                    citation_title = inside_metadata.get("title", "")
                                    citation_url = inside_metadata.get("url", "")
                                    new_text = f' **[[""]]({citation_url} "{citation_title}")** '
                                    len_last_citation = len(citation)
                                else:
                                    new_text = part[len_last_content:]
                                len_last_content = len(part)
                        else:
                            text = content.get("text", "")
                            if outer_content_type == "code" and last_content_type != "code":
                                new_text = "\n```" + recipient + "\n" + text[len_last_content:]
                            elif outer_content_type == "execution_output" and last_content_type != "execution_output":
                                new_text = "\n```" + "Output" + "\n" + text[len_last_content:]
                            else:
                                new_text = text[len_last_content:]
                            len_last_content = len(text)
                        if last_content_type == "code" and outer_content_type != "code":
                            new_text = "\n```\n" + new_text
                        elif last_content_type == "execution_output" and outer_content_type != "execution_output":
                            new_text = "\n```\n" + new_text
                        if recipient == "dalle.text2im" and last_recipient != "dalle.text2im":
                            new_text = "\n```" + "json" + "\n" + new_text
                        delta = {"content": new_text}
                        last_content_type = outer_content_type
                        last_recipient = recipient
                        if completion_tokens >= max_tokens:
                            delta = {}
                            finish_reason = "length"
                            end = True
                    elif status == "finished_successfully":
                        if content.get("content_type") == "multimodal_text":
                            parts = content.get("parts", [])
                            delta = {}
                            for part in parts:
                                if isinstance(part, str):
                                    continue
                                inner_content_type = part.get('content_type')
                                if inner_content_type == "image_asset_pointer":
                                    last_content_type = "image_asset_pointer"
                                    file_id = part.get('asset_pointer').replace('file-service://', '')
                                    logger.debug(f"file_id: {file_id}")
                                    image_download_url = await service.get_download_url(file_id)
                                    logger.debug(f"image_download_url: {image_download_url}")
                                    if image_download_url:
                                        delta = {"content": f"\n```\n![image]({image_download_url})\n"}
                                    else:
                                        delta = {"content": f"\n```\nFailed to load the image.\n"}
                        elif message.get("end_turn"):
                            part = content.get("parts", [])[0]
                            new_text = part[len_last_content:]
                            if not new_text:
                                matches = re.findall(r'\(sandbox:(.*?)\)', part)
                                if matches:
                                    file_url_content = ""
                                    for i, sandbox_path in enumerate(matches):
                                        file_download_url = await service.get_response_file_url(conversation_id, message_id, sandbox_path)
                                        if file_download_url:
                                            file_url_content += f"\n```\n![File {i+1}]({file_download_url})\n"
                                    delta = {"content": file_url_content}
                                else:
                                    delta = {}
                            else:
                                delta = {"content": new_text}
                            finish_reason = "stop"
                            end = True
                        else:
                            last_message_id = None
                            len_last_content = 0
                            continue
                    else:
                        continue
                    last_message_id = message_id
                    if not end and not delta.get("content"):
                        delta = {"role": "assistant", "content": ""}
                    chunk_new_data["choices"][0]["delta"] = delta
                    chunk_new_data["choices"][0]["finish_reason"] = finish_reason
                    if not service.history_disabled:
                        chunk_new_data.update({
                            "message_id": message_id,
                            "conversation_id": conversation_id,
                        })
                    completion_tokens += 1
                    yield f"data: {json.dumps(chunk_new_data)}\n\n"
                elif chunk.startswith("data: [DONE]"):
                    yield "data: [DONE]\n\n"
                else:
                    continue
            except Exception as e:
                if chunk.startswith("data: "):
                    chunk_data = json.loads(chunk[6:])
                    if chunk_data.get("error"):
                        error = f"{chunk_data.get('error')}"
                        delta = {"role": "assistant", "content": error + "（服务端请求失败，请重新请求或者更换模型再试吧！）"}
                        chunk_new_data = {
                            "id": chat_id,
                            "object": "chat.completion.chunk",
                            "created": created_time,
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": delta,
                                    "logprobs": None,
                                    "finish_reason": finish_reason
                                }
                            ],
                            "system_fingerprint": system_fingerprint
                        }
                        logger.error(f"Error: {chunk_data.get('error')}")
                        yield f"data: {json.dumps(chunk_new_data)}\n\n"
                        yield "data: [DONE]\n\n"
                        break
                else:
                    logger.error(f"Error: {chunk}, details: {str(e)}")
                continue
    except Exception as e:
        logger.error(f"Server error, {str(e)}")
        raise Exception("Server error")


async def api_messages_to_chat(service, api_messages, ori_model_name):
    file_tokens = 0
    chat_messages = []
    contains_url = False
    enable_search_models = 'gpt-3.5' not in ori_model_name and 'claude-3' not in ori_model_name
    if enable_system_prompt:
        api_messages.append({
            "role": "system",
            "content": system_prompt.format(model=ori_model_name, time=time.strftime("%Y-%m-%d %H:%M:%S"))
        })
        logger.info("成功注入系统提示信息！")
    if 'gpt-4o' in ori_model_name and 'gpt-4o-mini' not in ori_model_name:
        api_enable_search = enable_search and enable_gpt4o_search
    else:
        api_enable_search = enable_search and enable_search_models

    if api_enable_search:
        all_urls = deque(maxlen=max_file_num)
        url_positions = []
        extractor = URLExtract()

        for i, message in enumerate(api_messages):
            content = message.get("content", "")
            role = message.get("role", "assistant")
            is_search = str(content).strip().startswith(enable_search_prefix) and role not in ["assistant", "system"]
            if not isinstance(content, list) and is_search:
                urls = extractor.find_urls(str(content), True)
                urls = [url for url in urls if url.startswith(('https', 'http'))][:max_file_num]
                message["content"] = content.strip()
                url_positions.extend([(i, urls)])
                all_urls.extend(urls)

        all_urls = list(all_urls)
        contains_url = bool(all_urls)
        if len(all_urls) > 0:
            logger.info(f"当前请求消息里的包含的URLS:{all_urls}")
        # 将列表转换为字典
        final_positions = dict(url_positions)

    for index, api_message in enumerate(api_messages):
        role = api_message.get('role')
        content = api_message.get('content')
        if isinstance(content, list):
            parts = []
            attachments = []
            content_type = "multimodal_text"
            for i in content:
                if i.get("type") == "text":
                    parts.append(i.get("text"))
                elif i.get("type") == "image_url":
                    image_url = i.get("image_url")
                    url = image_url.get("url")
                    detail = image_url.get("detail", "auto")
                    file_content, mime_type = await get_file_content(url)
                    file_meta = await service.upload_file(file_content, mime_type)
                    if file_meta:
                        file_id = file_meta["file_id"]
                        file_size = file_meta["size_bytes"]
                        file_name = file_meta["file_name"]
                        mime_type = file_meta["mime_type"]
                        use_case = file_meta["use_case"]
                        if mime_type.startswith("image/"):
                            width, height = file_meta["width"], file_meta["height"]
                            file_tokens += await calculate_image_tokens(width, height, detail)
                            parts.append({
                                "content_type": "image_asset_pointer",
                                "asset_pointer": f"file-service://{file_id}",
                                "size_bytes": file_size,
                                "width": width,
                                "height": height
                            })
                            attachments.append({
                                "id": file_id,
                                "size": file_size,
                                "name": file_name,
                                "mime_type": mime_type,
                                "width": width,
                                "height": height
                            })
                        else:
                            if use_case == "my_files":
                                await service.check_upload(file_id)
                            file_tokens += file_size // 1000
                            attachments.append({
                                "id": file_id,
                                "size": file_size,
                                "name": file_name,
                                "mime_type": mime_type,
                            })
            metadata = {
                "attachments": attachments
            }

        # 当模型为3.5或者claude 或者 文本不包含url的时候，直接请求
        elif not api_enable_search or not contains_url:
            content_type = "text"
            parts = [content]
            metadata = {}

        else:
            metadata = {}
            parts = []
            attachments = []
            tem_urls = []
            content_type = "multimodal_text"
            all_urls = final_positions.get(index, [])

            for url in all_urls:
                file_content, mime_type = await get_file_content(url)
                file_meta = await service.upload_file(file_content, mime_type)
                if file_meta:
                    tem_urls.append(url)
                    file_id = file_meta["file_id"]
                    file_size = file_meta["size_bytes"]
                    file_name = file_meta["file_name"]
                    mime_type = file_meta["mime_type"]
                    if mime_type.startswith("image/"):
                        width, height = file_meta["width"], file_meta["height"]
                        file_tokens += await calculate_image_tokens(width, height, "auto")
                        parts.append({
                            "content_type": "image_asset_pointer",
                            "asset_pointer": f"file-service://{file_id}",
                            "size_bytes": file_size,
                            "width": width,
                            "height": height
                        })
                        attachments.append({
                            "id": file_id,
                            "size": file_size,
                            "name": file_name,
                            "mime_type": mime_type,
                            "width": width,
                            "height": height
                        })
                    else:
                        file_tokens += file_size // 1000
                        attachments.append({
                            "id": file_id,
                            "size": file_size,
                            "name": file_name,
                            "mime_type": mime_type,
                        })

            if attachments:
                metadata = {
                    "attachments": attachments
                }
                # 删除content里的url，防止影响信息
                content = reduce(lambda text, url: text.replace(url, ''), tem_urls, content).strip()
            parts.append(content)

        chat_message = {
            "id": f"{uuid.uuid4()}",
            "author": {"role": role},
            "content": {"content_type": content_type, "parts": parts},
            "metadata": metadata
        }
        chat_messages.append(chat_message)
    text_tokens = await num_tokens_from_messages(api_messages, service.resp_model)
    prompt_tokens = text_tokens + file_tokens
    return chat_messages, prompt_tokens
