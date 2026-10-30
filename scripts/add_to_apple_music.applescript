-- 指定した回以降のオンエア曲を、Apple Music のプレイリストへ追加する。
-- カタログの検索は find_apple_music_tracks.py が行い、すでにある曲は追加しない。

property selectorChoices : {"鈴木もぐら", "水川かたまり", "リスナー", "池田直人", "岡野陽一", "その他", "すべて"}
property pageWait : 4
property maxSkips : 60
property libraryLeftovers : {}

on run
	set libraryLeftovers to {}
	set startEpisode to askEpisode()
	set selectorName to askSelector()
	set playlistName to askPlaylist()

	set tempFolder to POSIX path of (path to temporary items)
	set existingPath to tempFolder & "onair_existing.tsv"
	writeExisting(playlistName, existingPath)

	set finderPath to scriptFolder() & "find_apple_music_tracks.py"
	set searchCommand to "PYTHONIOENCODING=utf-8 /usr/bin/python3 " & quoted form of finderPath & ¬
		" --from " & startEpisode & " --selector " & quoted form of selectorName & ¬
		" --existing " & quoted form of existingPath
	with timeout of 7200 seconds
		set searchResult to do shell script searchCommand
	end timeout

	set foundItems to {}
	set missingItems to {}
	set existingCount to 0
	repeat with resultLine in paragraphs of searchResult
		set fields to splitText(resultLine as text, tab)
		if (count of fields) ≥ 5 then
			set status to item 1 of fields
			if status is "found" then
				set end of foundItems to fields
			else if status is "not_found" then
				set end of missingItems to ("#" & item 2 of fields & " " & item 3 of fields & " / " & item 4 of fields)
			else
				set existingCount to existingCount + 1
			end if
		end if
	end repeat

	if (count of foundItems) is 0 then
		showReport(playlistName, {}, {}, missingItems, existingCount)
		return
	end if

	display dialog ((count of foundItems) as text) & "曲を「" & playlistName & "」へ追加します。" & return & ¬
		"曲はライブラリを経由して追加し、追加後にライブラリから削除します。元からある曲は削除しません。" & return & "再生中の曲は止まります。" & return & ¬
		"追加中は Music アプリを操作しないでください。音量は処理の間だけ0にします。" buttons {"キャンセル", "追加する"} default button "追加する" cancel button "キャンセル"

	set addedItems to {}
	set failedItems to {}
	tell application "Music"
		set savedVolume to sound volume
		set savedShuffle to shuffle enabled
		stop
		set shuffle enabled to false
		set sound volume to 0
	end tell
	try
		repeat with fields in foundItems
			set label to "#" & item 2 of fields & " " & item 3 of fields & " / " & item 4 of fields
			if addTrack(item 5 of fields, item 6 of fields, item 7 of fields, playlistName) then
				set end of addedItems to label
			else
				set end of failedItems to label
			end if
		end repeat
	end try
	tell application "Music"
		stop
		set sound volume to savedVolume
		set shuffle enabled to savedShuffle
	end tell

	showReport(playlistName, addedItems, failedItems, missingItems, existingCount)
end run

on askEpisode()
	repeat
		set answer to text returned of (display dialog "何回以降の曲を追加しますか？" default answer "206" buttons {"キャンセル", "次へ"} default button "次へ" cancel button "キャンセル")
		try
			set episode to answer as integer
			if episode ≥ 206 then return episode
		end try
		display dialog "206以上の回番号を入力してください。" buttons {"OK"} default button "OK"
	end repeat
end askEpisode

on askSelector()
	set picked to choose from list selectorChoices with prompt "選曲者を選んでください。" default items {item 1 of selectorChoices}
	if picked is false then error number -128
	return item 1 of picked
end askSelector

on askPlaylist()
	set answer to text returned of (display dialog "追加先のプレイリスト名を入力してください。" default answer "空気階段の踊り場" buttons {"キャンセル", "次へ"} default button "次へ" cancel button "キャンセル")
	tell application "Music"
		if not (exists user playlist answer) then
			display dialog "「" & answer & "」はありません。新しく作りますか？" buttons {"キャンセル", "作成する"} default button "作成する" cancel button "キャンセル"
			make new user playlist with properties {name:answer}
		end if
		if smart of user playlist answer then error "スマートプレイリストには追加できません。"
	end tell
	return answer
end askPlaylist

on writeExisting(playlistName, filePath)
	tell application "Music"
		set trackNames to name of tracks of user playlist playlistName
		set trackArtists to artist of tracks of user playlist playlistName
	end tell
	set output to ""
	repeat with i from 1 to count of trackNames
		set output to output & (item i of trackNames) & tab & (item i of trackArtists) & linefeed
	end repeat
	set fileHandle to open for access (POSIX file filePath) with write permission
	set eof fileHandle to 0
	write output to fileHandle as «class utf8»
	close access fileHandle
end writeExisting

-- Music アプリにはカタログの曲を直接追加する命令がない。
-- 購読曲は再生中の曲をライブラリへ複製できるので、ライブラリを経由して追加する。
-- 新しく入れた曲はプレイリストへ入れたあとでライブラリから消す。元からある曲は消さない。
on addTrack(trackUrl, expectedName, expectedArtist, playlistName)
	set addedToLibrary to false
	try
		set libraryTrack to findInLibrary(expectedName, expectedArtist)
		if libraryTrack is missing value then
			if not playCatalogTrack(trackUrl, expectedName) then return false
			tell application "Music"
				set countBefore to count of tracks of library playlist 1
				set librarySource to first source whose kind is library
				duplicate current track to librarySource
				stop
			end tell
			repeat 10 times
				set libraryTrack to findInLibrary(expectedName, expectedArtist)
				if libraryTrack is not missing value then exit repeat
				delay 1
			end repeat
			if libraryTrack is missing value then return false
			-- 検索の遅れで元からある曲を消さないよう、曲数が増えたときだけ削除の対象にする。
			tell application "Music" to set addedToLibrary to (count of tracks of library playlist 1) > countBefore
		end if
		tell application "Music"
			set trackId to persistent ID of libraryTrack
			duplicate libraryTrack to user playlist playlistName
		end tell
	on error
		tell application "Music" to stop
		return false
	end try
	if addedToLibrary then removeFromLibrary(trackId, expectedName & " / " & expectedArtist)
	return true
end addTrack

on removeFromLibrary(trackId, label)
	try
		tell application "Music"
			delete (first track of library playlist 1 whose persistent ID is trackId)
		end tell
	on error
		set end of libraryLeftovers to label
	end try
end removeFromLibrary

on findInLibrary(expectedName, expectedArtist)
	tell application "Music"
		set found to (search library playlist 1 for expectedName only songs)
		repeat with candidate in found
			if name of candidate is expectedName and artist of candidate is expectedArtist then return contents of candidate
		end repeat
	end tell
	return missing value
end findInLibrary

-- 曲の URL を開いて再生するとアルバムの先頭から始まるので、目的の曲まで送る。
on playCatalogTrack(trackUrl, expectedName)
	set songId to text ((offset of "?i=" in trackUrl) + 3) thru -1 of trackUrl
	tell application "Music"
		open location "music://music.apple.com/jp/song/" & songId
		delay pageWait
		play
		delay 2
		repeat maxSkips times
			if name of current track is expectedName then return true
			next track
			delay 1
		end repeat
		stop
	end tell
	return false
end playCatalogTrack

on showReport(playlistName, addedItems, failedItems, missingItems, existingCount)
	set body to "プレイリスト: " & playlistName & return & ¬
		"追加: " & (count of addedItems) & "曲" & return & ¬
		"すでにあるため省略: " & existingCount & "曲" & return & ¬
		"追加に失敗: " & (count of failedItems) & "曲" & return & ¬
		"Apple Music で見つからない: " & (count of missingItems) & "曲" & return & ¬
		"ライブラリから削除できなかった: " & (count of libraryLeftovers) & "曲"
	set details to body & return & return & "追加した曲" & return & joinText(addedItems, return) & ¬
		return & return & "追加に失敗した曲" & return & joinText(failedItems, return) & ¬
		return & return & "見つからなかった曲" & return & joinText(missingItems, return) & ¬
		return & return & "ライブラリから削除できなかった曲" & return & joinText(libraryLeftovers, return)
	set reportPath to writeReport(details)
	display dialog body buttons {"詳細を開く", "閉じる"} default button "閉じる"
	if button returned of result is "詳細を開く" then do shell script "open " & quoted form of reportPath
end showReport

-- 結果は scripts/results/ に日時つきの名前で残す。
on writeReport(details)
	set resultsFolder to scriptFolder() & "results/"
	do shell script "mkdir -p " & quoted form of resultsFolder
	set reportPath to resultsFolder & "onair_report_" & (do shell script "date +%Y%m%d_%H%M%S") & ".txt"
	set fileHandle to open for access (POSIX file reportPath) with write permission
	write details to fileHandle as «class utf8»
	close access fileHandle
	return reportPath
end writeReport

on scriptFolder()
	set scriptPath to POSIX path of (path to me)
	return do shell script "dirname " & quoted form of scriptPath & " | sed 's#$#/#'"
end scriptFolder

on splitText(sourceText, delimiter)
	set saved to AppleScript's text item delimiters
	set AppleScript's text item delimiters to delimiter
	set parts to text items of sourceText
	set AppleScript's text item delimiters to saved
	return parts
end splitText

on joinText(parts, delimiter)
	set saved to AppleScript's text item delimiters
	set AppleScript's text item delimiters to delimiter
	set joined to parts as text
	set AppleScript's text item delimiters to saved
	return joined
end joinText
