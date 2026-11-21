# Meowcal Sub 2 privacy policy

[简体中文](privacy.zh-CN.md)

This policy covers the Meowcal Sub 2 Windows app, provided by Shanxin Li.

## Watching a video

When you start a session, the app reads the subtitle area you select. It can also sample the surrounding player picture to detect motion and ask Windows for audio session activity and volume levels to help detect pauses. It does not record microphone audio or the soundtrack. Text recognition, dialogue matching and translation run on your PC. The app does not send screen images, recognized dialogue or translations to a cloud translation service.

## Subtitle services and downloads

If you search for subtitle files, the services you enable (OpenSubtitles, SubDL or ASSRT) receive the title, language choices, search or download identifiers, and the credentials required by that service. Optional TMDb requests retrieve title metadata and posters. Downloading models or runtime components contacts their download hosts. The Studio can request fonts from Google Fonts. Installed copies can contact their distribution channel for app updates. Each destination receives normal connection information, including your IP address.

You can turn off individual subtitle sources and TMDb in Settings. Live screen translation uses a locally installed translation model and does not require a subtitle provider account.

## Files on your PC

The app stores your settings, downloaded subtitles, edited copies, caches and logs under your Windows user account. Provider credentials are saved in the local configuration file as plain text. Logs can include search terms, titles, file names and errors. Running the backend in verbose mode can also save recognized dialogue and subtitle lines in the logs. Optional per-capture diagnostics send recognition data to the Studio on your own PC.

To stop capture, stop the session or quit the app. To clear saved credentials, remove them in Settings and save. After quitting, you can remove the app's own local files. The [user guide](../user-guide.md#stored-data-and-connections) describes the storage and log locations. Local changes do not remove information already sent to a subtitle service.

## Support and contact

If you send a support request, share only what you are comfortable disclosing. GitHub issues are public. Keep screenshots of private viewing, full logs, passwords and provider keys out of reports. For a private question about your data, contact the maintainer at [shanxin@u.nus.edu](mailto:shanxin@u.nus.edu).
