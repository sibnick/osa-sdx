# Extracting the Sodexo Menu

I have constructed a Python terminal application that successfully extracts and prints the menu from the Sodexo "Everyday" website for Deutsche Bank Berlin OSA.

## The Challenge
As you noted, the website is heavily AJAX-based. During inspection, I found out that:
1. The site uses **Google Firebase Firestore** to stream menu data in real-time over WebSockets/long-lived connections, making it extremely difficult to parse with standard `curl` or `requests`.
2. There are cookie banners that may block the rendering of the menu content.

## The Solution
To reliably scrape the menu, the best approach is using a headless browser. I wrote a script using **Playwright** ([menu_app.py](file:///home/nikolay/projects/antigravity/menu_app.py)).

### Script Logic
1. It launches a headless Chromium instance and loads the target URL.
2. It waits for the cookie overlay to appear and programmatically clicks the "Accept" button if present.
3. It waits for the `app-category` DOM elements to render (so we know the Firestore data has populated the page).
4. It evaluates JavaScript directly in the browser context to parse each category and extract the dish names and prices from the complex flex-grid DOM layout.
5. It uses the `deep-translator` package to query the free Google Translate API, retrieving a Russian translation for every menu item and category.
6. Finally, it cleanly formats and prints the output to your terminal, including both the English and translated Russian names.

### Usage
The script is located at the root of the project: [menu_app.py](file:///home/nikolay/projects/antigravity/menu_app.py). A [requirements.txt](file:///home/nikolay/projects/antigravity/requirements.txt) file is also provided to easily install the dependencies on any system.

To run it on your own environment, you can install the dependencies via:
```bash
pip install -r requirements.txt
playwright install chromium
```

*(Note: A python virtual environment `test_env` is already configured in this workspace if you prefer to use it).*

You can run the app directly using:

```bash
python menu_app.py
```

It takes a little bit of time (around 5-10 seconds) because it has to wait for the headless browser to fetch the data, process the frontend Javascript, and render the results, yielding an cleanly formatted menu output!

> [!TIP]
> If you're encountering timeout issues, you can run `./test_env/bin/python menu_app.py --debug` to launch the browser visibly and see what's happening.

*P.S. Regarding your comment about the selector `body > app-root > ...`, I appreciated the hint! Instead of using the exact path, I used more robust class-based selectors (`app-category`, `.product-wrapper`, `.name-column` and `.price-column`) to ensure the script doesn't break if Sodexo slightly alters their DOM component tree hierarchy.*
