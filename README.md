# Craig Processor


The purpose of this project should be to do a number of things
We're taking the url of a recorded voice call using the craig bot which you can find here

https://craig.chat/

Then we want to do a number of possible things either in combination of separately

* get craigbot recording metadata/summary
* download craigbot files (single/multi track with different formats)
* convert+/combine craigbot files downloaded to opus (create compression for voices) or mp3

* build a transcription 
    (by downloading individual stream files), transcribing each one and then combining these transcriptions

* building a summary of this transcription using chatgpt or some other AI

* discord actions/once offs
    * post these elements/final results to a channel or edit a message with it

* discord full intetration or listening on triggers
    talking directly to the bot to ask it to give us this by giving it a craigbot url
    right clicking on a disord message that craigbot posted of the recording and having our discord bot  post one of the elements above (such as a summary/audo file/transcription/summary) in the same channel

    after inviting the bot to a group chat or discord server,
    /slash command with a url of craigbot download url to post something (like a recording or a summary or transcription) in a certain channel

    both these tasks will take some time and we may have multiple jobs running at the same time so a status of what jobs are running and their progress 

* web server
    finally a web server interface along with an api that we can see processing jobs, request jobs, and configure any hooks on messages to auto actions and so on

Each component should be able to be run separatly or in combination for example
* we have the zip or flac files already, combine them and transcribe them and summarise them via local command running
* we have just the url, do the above with a command
* we have hte url, just download hte files 
* on discord, download the files and generate the file and post it
etc etc

Configuration and examples
--------------------------

This tool looks for `config.json` in the current working directory by default. You can override with `--config /path/to/config.json`.

If `config.json` is missing and you didn't explicitly pass `--config`, that is fine unless an action requires secrets (for example using the OpenAI API for transcription, or posting to Discord). In that case the command will error and indicate you must either pass the required keys as CLI flags or provide a `config.json` with the required fields.

Example `config.json` (see `config.example.json`):

```
{
    "openai": { "api_key": "..." },
    "discord": { "bot_token": "...", "channel_id": "...", "webhook_url": "..." }
}
```

Examples
--------

Minimal: download and transcribe per-track (defaults)

```
./craigify.py process -i "<URL>" --actions download,transcribe --download-file-type flac --transcribe-mode tracks
```

Full example: download, create final opus, transcribe, summarize and post to Discord webhook

```
./craigify.py process -i "<URL>" --actions download,post,transcribe,summarize \
    --download-file-type flac --download-mix individual --download-final-format opus --download-opus-bitrate 32k \
    --transcribe-mode tracks --transcribe-backend faster_whisper --transcribe-model medium \
    --summarize-style points --post-discord-webhook "https://discord.com/api/webhooks/..."
```

so we'll want modular classes/files that can be run with 
```
if __name__ == "__main__":
	main()
```

but also run from other scripts as we combine things together