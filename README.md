# BruinsTicketsScanner

This project periodically scans across multiple ticket sale platforms (Stubhub and Seatgeek) and looks for ‘cheap’ Boston Bruins games in Boston, MA.
A ‘cheap’ game is one in which the lowest ticket price for that game is under a set price threshold. These results are automatically saved to the ‘output.txt’ file.

If a game is found which has a minimum ticket price under another threshold, a text message is sent to a phone number notifying them of the cheap game.
