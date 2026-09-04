# StrikeSnipe - A pretty nice program :3

StrikeSnipe monitors CSFloat listings and sends Discord alerts when an item appears to be priced below its estimated resale value. It is designed to be ONLY an alerting tool only: it does not automate any activities...

## Supported categories
- Skins: Compares potential listings with past sales, similar comparable listings, and provides a rough estimate of value.
- Cases, Capsules, and unapplied stickers: These are compared to identical listings to provide a mostly accurate price.
- Charms: exact charm name, with `keychain_pattern` are separated when possible so pattern variants are not blindly mixed.
- Souvenirs are by default excluded. (often greatly varry in prices)

## Current Features (9/3/2026)
- Auto Scan: Continuously scans for listings while toggled on
- Stop Scanner: Stops scanner (shocker)
- Scan Once: Scans a single time, niche use and mainly used in testing and or debugging.
- Auctions only: toggles between only evaluating auctions or BINS and auctions. 

- Clear Listings: Clears scanned unique listings
- Clear Sales: Clears the scanned past sales for potential canidates
- FULL RESET: This will fully reset the scanner (excluding configs) and wips cached data

- Test CSFloat: Tests sending a request through API to CSfloat.com
- Test Discord: Tests sending a message through your discord webhook.

## Usage
1. You need to duplicate the .env.default file and rename it to .env       This is so I can share it without accidently sending my own details :D

2. Fill in your own values for the API key and Discord webhook url in your .env file. (The program will not be able to reconize your API key or Discord webhook url if you do not place them into .env)

3. Configure the settings, either use the "default" settings or adjust them to your own likings.

4. Only after the above are completed is when you can start the program by either running the "START.bat" file by clicking on it, or through the terminal with .\START.bat

Finally this will download the requirments if they are missing from requirements.txt (I did not create them) and launch the terminal (view api calls) and open your default browser to http://127.0.0.1:8787/ where you will view the dash board.

From the dashboard you can also edit, toggle, and view the controls that are adjustable in the .env file (no need to restart the program when editing the configs in .env !)

## Disclaimer 

- Use this at your own risk, nothing is gaurenteed and a flip that shows may be profit may not acually be profit and rather just and error. Always double check listings and thus the developer is not responsible for any errors are actions done by the users

- Unfortuantly I don't have all the knowledge when it comes to this so there was ai used to build upon the foundation of the project, and aswell as integrating the dashboard wasn't done by me (aka i don't want to learn html right now :P). I am not claiming to have written everything in this project and would just like to acknoledge and give credit to pookie bear claude and copilot with helping advance this project to the current state :D