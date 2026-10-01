# Authorized Media Conversion API

API REST em Python 3.12+ para **analisar e converter mídias autorizadas pelo usuário**. A análise usa `ffprobe` e só retorna qualidades, resoluções, FPS, codecs, formatos e bitrates encontrados na mídia. A conversão é executada em jobs assíncronos com `ffmpeg`.

## Requisitos

- Python 3.12+
- FFmpeg e FFprobe instalados e disponíveis no `PATH`
- Para Ubuntu/Debian: `sudo apt-get install ffmpeg`

## Instalação e execução

```bash
cd video-media-api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Todos os endpoints de mídia exigem o cabeçalho `X-API-Key`. O endpoint `/health` permanece público.

Swagger: <http://localhost:8000/docs>  
OpenAPI JSON: <http://localhost:8000/openapi.json>

## Endpoints

### `POST /analyze`

Envie um `multipart/form-data` com **exatamente um** dos campos:

- `file`: upload da mídia
- `source`: URL HTTP/HTTPS pública da mídia

Exemplo:

```bash
curl -H 'X-API-Key: 9e8ZyWghoMoWUtt0oK1crfqBbGpspArVJ217pOr98vs' -F 'file=@video.mp4' http://localhost:8000/analyze
# ou
curl -H 'X-API-Key: 9e8ZyWghoMoWUtt0oK1crfqBbGpspArVJ217pOr98vs' -F 'source=https://example.test/video.mp4' http://localhost:8000/analyze
```

O retorno inclui `title`, `duration_seconds`, `size_bytes`, `resolutions`, `qualities`, `fps`, `video_codecs`, `audio_codecs`, `video_formats`, `audio_formats`, `audio_bitrates_kbps` e os streams brutos do `ffprobe`. Nenhuma opção fictícia é adicionada. Se a mídia não declarar bitrate de áudio, a API expõe os bitrates convencionais suportados para permitir a codificação.

### `POST /convert`

Também recebe `multipart/form-data`, com `file` ou `source`, mais:

- `tipo`: `video` ou `audio`
- `formato`: vídeo `mp4`, `webm`, `mkv`, `mov`, `avi`, `flv`, `mpeg`, `ts`; áudio `mp3`, `m4a`, `wav`, `flac`, `ogg`, `opus`
- `qualidade`: por exemplo `1080p`, apenas uma qualidade detectada
- `resolucao`: por exemplo `1920x1080`, apenas uma resolução detectada
- `fps`: apenas um FPS detectado
- `codec`: codec detectado na origem
- `bitrate`: bitrate de áudio em kbps detectado/disponível

Os parâmetros opcionais devem ser escolhidos a partir do retorno de `/analyze`; caso contrário, a API responde `422` e não cria o job.
Além disso, o codec precisa ser compatível com o formato de saída; incompatibilidades são rejeitadas antes de iniciar o FFmpeg.

Resposta `202`:

```json
{"job_id":"...","status":"queued","progress":0,"speed":null,"eta_seconds":null,"error":null,"filename":null}
```

### `GET /jobs/{job_id}`

Retorna `queued`, `processing`, `completed` ou `failed`, além de progresso percentual, velocidade e ETA estimado.

### `GET /download/{job_id}`

Baixa o arquivo somente quando o job estiver `completed`.

## Segurança e operação

- Uploads e URLs têm limites configuráveis (`MEDIA_API_MAX_UPLOAD_BYTES`, `MEDIA_API_MAX_URL_BYTES`).
- Somente URLs `http`/`https` sem credenciais embutidas são aceitas.
- Não são aceitos caminhos locais enviados pelo cliente; isso evita path traversal e acesso arbitrário ao filesystem.
- Nomes de upload são normalizados com `Path.name` e whitelist de caracteres.
- Cada saída usa UUID e é criada exclusivamente dentro de `media/outputs`.
- Arquivos de origem são apagados ao fim da análise ou do job.
- A tarefa de limpeza remove arquivos antigos de `uploads`, `outputs` e `temp` conforme `MEDIA_API_CLEANUP_HOURS`.
- Jobs são limitados por `MEDIA_API_MAX_CONCURRENT_JOBS`.
- A API processa somente mídia que o usuário está autorizado a fornecer e converter.

## Configuração do FFmpeg

Use `MEDIA_API_FFMPEG_BIN` e `MEDIA_API_FFPROBE_BIN` para informar caminhos absolutos quando os binários não estiverem no `PATH`. O comando de conversão é montado com argumentos separados, sem shell, reduzindo risco de injeção de comandos.

## Testes

```bash
pytest -q
```
