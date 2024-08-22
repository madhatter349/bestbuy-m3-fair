import requests
import json
import sqlite3
from datetime import datetime

# Database setup
DB_NAME = 'bestbuy_stock.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS stock_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT,
        store_name TEXT,
        city TEXT,
        state TEXT,
        zip_code TEXT,
        pickup_date TEXT,
        quantity INTEGER,
        timestamp TEXT
    )
    ''')
    conn.commit()
    conn.close()

def fetch_bestbuy_data():
    cookies = {}
    headers = {
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'accept-language': 'en-US,en;q=0.9',
        'origin': 'https://www.bestbuy.com',
        'priority': 'u=1, i',
        'referer': 'https://www.bestbuy.com/product/apple-macbook-air-13-inch-laptop-m3-chip-8gb-memory-256gb-ssd-midnight/6565837/openbox?condition=fair',
        'sec-ch-ua': '"Not)A;Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    }
    json_data = {
        'locationId': '1531',
        'zipCode': '10003',
        'showOnShelf': True,
        'lookupInStoreQuantity': False,
        'xboxAllAccess': False,
        'consolidated': False,
        'showOnlyOnShelf': False,
        'showInStore': False,
        'pickupTypes': ['UPS_ACCESS_POINT', 'FEDEX_HAL'],
        'onlyBestBuyLocations': True,
        'items': [
            {
                'sku': '6565832',
                'condition': '2',
                'quantity': 1,
                'itemSeqNumber': '5',
                'reservationToken': None,
                'selectedServices': [],
                'requiredAccessories': [],
                'isTradeIn': False,
                'isLeased': False,
            },
        ],
    }
    response = requests.post('https://www.bestbuy.com/productfulfillment/c/api/2.0/storeAvailability', cookies=cookies, headers=headers, json=json_data)
    return json.loads(response.text)

def process_data(data):
    stores = {loc['id']: loc for loc in data['ispu']['locations']}
    stock_info = []
    for item in data['ispu']['items']:
        sku = item['sku']
        for loc in item['locations']:
            store_id = loc['locationId']
            store = stores.get(store_id, {})
            avail = loc.get('availability', {})
            if avail:
                stock_info.append({
                    'sku': sku,
                    'store_name': store.get('name', 'Unknown'),
                    'city': store.get('city', 'Unknown'),
                    'state': store.get('state', 'Unknown'),
                    'zip_code': store.get('zipCode', 'Unknown'),
                    'pickup_date': avail.get('minDate', 'N/A'),
                    'quantity': avail.get('availablePickupQuantity', 0)
                })
    return stock_info

def update_database(stock_info):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    timestamp = datetime.now().isoformat()
    for item in stock_info:
        cursor.execute('''
        INSERT INTO stock_data (sku, store_name, city, state, zip_code, pickup_date, quantity, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (item['sku'], item['store_name'], item['city'], item['state'], item['zip_code'], item['pickup_date'], item['quantity'], timestamp))
    conn.commit()
    conn.close()

def check_for_changes():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
    SELECT * FROM stock_data
    WHERE id IN (SELECT MAX(id) FROM stock_data GROUP BY sku, store_name)
    ORDER BY sku, store_name
    ''')
    latest_data = cursor.fetchall()
    
    cursor.execute('''
    SELECT * FROM stock_data
    WHERE id IN (SELECT MAX(id) FROM stock_data WHERE id NOT IN (SELECT MAX(id) FROM stock_data GROUP BY sku, store_name) GROUP BY sku, store_name)
    ORDER BY sku, store_name
    ''')
    previous_data = cursor.fetchall()
    
    conn.close()
    
    changes = []
    for latest, previous in zip(latest_data, previous_data):
        if latest[6] != previous[6]:  # Compare quantities
            changes.append({
                'sku': latest[1],
                'store_name': latest[2],
                'city': latest[3],
                'state': latest[4],
                'previous_quantity': previous[6],
                'latest_quantity': latest[6],
                'timestamp': latest[7]
            })
    
    return changes

def save_stock_changes(changes):
    with open('stock_change_result.json', 'w') as f:
        json.dump(changes, f, indent=2)

def send_email(changes):
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    for change in changes:
        body_content = f"""
        <h2>Stock Change Alert</h2>
        <p>A stock change has been detected:</p>
        <ul>
            <li>SKU: {change['sku']}</li>
            <li>Store: {change['store_name']}, {change['city']}, {change['state']}</li>
            <li>Previous Quantity: {change['previous_quantity']}</li>
            <li>New Quantity: {change['latest_quantity']}</li>
            <li>Timestamp: {change['timestamp']}</li>
        </ul>
        """
        subject_title = f"Stock Change for SKU {change['sku']}"
        data = {
            'to': 'madhatter349@gmail.com',
            'subject': subject_title,
            'body': body_content,
            'type': 'text/html'
        }
        response = requests.post('https://www.cinotify.cc/api/notify', headers=headers, data=data)
        log_debug(f"Email sending status code: {response.status_code}")
        log_debug(f"Email sending response: {response.text}")
        if response.status_code != 200:
            log_debug(f"Failed to send email for SKU: {change['sku']}. Status code: {response.status_code}")
        else:
            log_debug(f"Email sent successfully for SKU: {change['sku']}")
    return True  # Return True if the process completes, even if some emails fail

def log_debug(message):
    with open('debug.log', 'a') as f:
        f.write(f"{datetime.now()}: {message}\n")

def main():
    log_debug("Script started")
    init_db()
    data = fetch_bestbuy_data()
    stock_info = process_data(data)
    update_database(stock_info)
    changes = check_for_changes()
    if changes:
        save_stock_changes(changes)
        send_email(changes)
        log_debug(f"Found {len(changes)} changes. Emails sent and results saved.")
    else:
        log_debug("No changes detected.")
    log_debug("Script finished")

if __name__ == "__main__":
    main()
