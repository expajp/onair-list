-- Apple Music のプレイリストを放送順に並べ替える。
-- 順番は sort_playlist_tracks.py が番組の一覧と照合して決める。

property programs : {¬
	{programId:"odoriba", programName:"空気階段の踊り場"}, ¬
	{programId:"ann0", programName:"マヂカルラブリーのオールナイトニッポン0(ZERO)"}}

on run
	set programKey to askProgram()
	set playlistName to askPlaylist()
	set trackCount to writeTracks(playlistName, (POSIX path of (path to temporary items)) & "onair_tracks.tsv")
	if trackCount is 0 then
		display dialog "「" & playlistName & "」に曲がありません。" buttons {"OK"} default button "OK"
		return
	end if

	set positions to {}
	set expectedNames to {}
	set orderedItems to {}
	set unmatchedItems to {}
	repeat with resultLine in paragraphs of orderCommandResult(programKey)
		set fields to splitText(resultLine as text, tab)
		if (count of fields) ≥ 4 then
			set end of positions to (item 1 of fields) as integer
			set end of expectedNames to item 3 of fields
			if item 2 of fields is "" then
				set end of unmatchedItems to item 3 of fields & " / " & item 4 of fields
			else
				set end of orderedItems to item 2 of fields & " " & item 3 of fields & " / " & item 4 of fields
			end if
		end if
	end repeat

	if (count of positions) is not trackCount then error "曲数が合わないため中止しました。"

	display dialog "「" & playlistName & "」の" & trackCount & "曲を放送順に並べ替えます。" & return & ¬
		"一覧と照合できない" & (count of unmatchedItems) & "曲は最後に並べます。" & return & ¬
		"処理中は Music アプリを操作しないでください。" buttons {"キャンセル", "並べ替える"} default button "並べ替える" cancel button "キャンセル"

	reorderTracks(playlistName, positions, expectedNames)
	showReport(playlistName, orderedItems, unmatchedItems)
end run

on askProgram()
	set names to {}
	repeat with program in programs
		set end of names to programName of program
	end repeat
	set picked to choose from list names with prompt "番組を選んでください。" default items {item 1 of names}
	if picked is false then error number -128
	repeat with program in programs
		if programName of program is item 1 of picked then return programId of program
	end repeat
end askProgram

on askPlaylist()
	set picked to choose from list sortablePlaylists() with prompt "並べ替えるプレイリストを選んでください。"
	if picked is false then error number -128
	return item 1 of picked
end askPlaylist

on sortablePlaylists()
	set playlistNames to {}
	tell application "Music"
		repeat with candidate in user playlists
			if class of candidate is user playlist and special kind of candidate is none and not smart of candidate then
				set end of playlistNames to name of candidate
			end if
		end repeat
	end tell
	return playlistNames
end sortablePlaylists

on writeTracks(playlistName, filePath)
	set trackNames to {}
	set trackArtists to {}
	tell application "Music"
		if (count of tracks of user playlist playlistName) > 0 then
			set trackNames to name of tracks of user playlist playlistName
			set trackArtists to artist of tracks of user playlist playlistName
		end if
	end tell
	set output to ""
	repeat with i from 1 to count of trackNames
		set output to output & (item i of trackNames) & tab & (item i of trackArtists) & linefeed
	end repeat
	set fileHandle to open for access (POSIX file filePath) with write permission
	set eof fileHandle to 0
	write output to fileHandle as «class utf8»
	close access fileHandle
	return count of trackNames
end writeTracks

on orderCommandResult(programKey)
	set tracksPath to (POSIX path of (path to temporary items)) & "onair_tracks.tsv"
	set sorterPath to scriptFolder() & "sort_playlist_tracks.py"
	return do shell script "PYTHONIOENCODING=utf-8 /usr/bin/python3 " & quoted form of sorterPath & ¬
		" --program " & programKey & " --tracks " & quoted form of tracksPath
end orderCommandResult

-- Music アプリの move は位置が安定しない。正しい順の複製を末尾に作り、確認してから元の曲を消す。
-- 複製と削除はプレイリストの中だけで行われ、ライブラリは変わらない。
on reorderTracks(playlistName, positions, expectedNames)
	set trackCount to count of positions
	tell application "Music"
		with timeout of 1800 seconds
			try
				repeat with position in positions
					duplicate (track (contents of position) of user playlist playlistName) to user playlist playlistName
				end repeat
				if (count of tracks of user playlist playlistName) is not (trackCount * 2) then error "複製した曲数が合いません。"
				set copiedNames to name of tracks (trackCount + 1) thru (trackCount * 2) of user playlist playlistName
				if copiedNames is not expectedNames then error "複製した曲の順番が合いません。"
			on error message
				-- 途中で失敗したら複製だけを消して元に戻す。
				repeat while (count of tracks of user playlist playlistName) > trackCount
					delete last track of user playlist playlistName
				end repeat
				error message & " プレイリストは元の順番のままです。"
			end try
			repeat trackCount times
				delete track 1 of user playlist playlistName
			end repeat
		end timeout
	end tell
end reorderTracks

on showReport(playlistName, orderedItems, unmatchedItems)
	set body to "プレイリスト: " & playlistName & return & ¬
		"放送順に並べた曲: " & (count of orderedItems) & "曲" & return & ¬
		"一覧と照合できず最後に並べた曲: " & (count of unmatchedItems) & "曲"
	set details to body & return & return & "放送順" & return & joinText(orderedItems, return) & ¬
		return & return & "照合できなかった曲" & return & joinText(unmatchedItems, return)
	set reportPath to writeReport(details)
	display dialog body buttons {"詳細を開く", "閉じる"} default button "閉じる"
	if button returned of result is "詳細を開く" then do shell script "open " & quoted form of reportPath
end showReport

-- 結果は scripts/results/ に日時つきの名前で残す。
on writeReport(details)
	set resultsFolder to scriptFolder() & "results/"
	do shell script "mkdir -p " & quoted form of resultsFolder
	set reportPath to resultsFolder & "sort_report_" & (do shell script "date +%Y%m%d_%H%M%S") & ".txt"
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
