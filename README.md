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

* discord integration
    talking directly to the bot to ask it to give us this by giving it a craigbot url
    right clicking on a disord message that craigbot posted of the recording and having our discord bot  post one of the elements above (such as a summary/audo file/transcription/summary) in the same channel

    after inviting the bot to a group chat or discord server,
    /slash command with a url of craigbot download url to post something (like a recording or a summary or transcription) in a certain channel

    both these tasks will take some time and we may have multiple jobs running at the same time so a status of what jobs are running and their progress 

Each component should be able to be run separatly or in combination for example
* we have the zip or flac files already, combine them and transcribe them and summarise them via local command running
* we have just the url, do the above with a command
* we have hte url, just download hte files 
* on discord, download the files and generate the file and post it
etc etc

so we'll want modular classes/files that can be run with 
```
if __name__ == "__main__":
	main()
```

but also run from other scripts as we combine things together