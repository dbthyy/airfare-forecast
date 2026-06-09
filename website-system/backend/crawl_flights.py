import os
import re
import time
import argparse
import hashlib
import logging
import datetime
from pathlib import Path
from time import sleep
import pandas as pd

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.edge.service import Service
from selenium.common.exceptions import WebDriverException

# ==========================================
# 1. CẤU HÌNH LOGGING SYSTEM (TỐI GIẢN)
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('crawl.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ==========================================
# 2. KHỞI TẠO THƯ MỤC LƯU TRỮ DỮ LIỆU
# ==========================================
DATA_DIR = Path('data/raw')
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ==========================================
# 3. THAM SỐ CẤU HÌNH MẶC ĐỊNH
# ==========================================
MAX_RETRIES   = 3          
RETRY_WAIT    = 10          
HEADLESS      = True        
CRAWL_DELAY   = 2          
EDGE_DRIVER_PATH = r"C:\WebDriver\msedgedriver.exe"

COLUMNS = [
    'id', 'brand', 'price', 'start_time', 'start_day', 'end_time', 'end_day',
    'trip_time', 'take_place', 'destination',
    'hand_luggage', 'checked_baggage', 'crawl_date'
]

# ==========================================
# 4. CÁC HÀM BỔ TRỢ HỆ THỐNG (HELPERS)
# ==========================================
def get_urls(places, days_ahead, specific_date=None):
    """Sinh danh sách URL Traveloka theo lộ trình và ngày mong muốn."""
    processed_places = [p if "SGN." in p else f"SGN.{p}" for p in places]
    
    if specific_date:
        return [
            f"https://www.traveloka.com/vi-vn/flight/fullsearch?ap={place}&dt={specific_date}.NA&ps=1.0.0&sc=ECONOMY"
            for place in processed_places
        ]
        
    today = datetime.date.today()
    return [
        f"https://www.traveloka.com/vi-vn/flight/fullsearch?ap={place}&dt={(today + datetime.timedelta(days=day_idx)).strftime('%d-%m-%Y')}.NA&ps=1.0.0&sc=ECONOMY"
        for place in processed_places
        for day_idx in range(1, days_ahead + 1)
    ]

def url_to_key(url):
    return hashlib.md5(url.encode()).hexdigest()[:12]

# ==========================================
# 5. KHỞI TẠO BROWSER ENGINE & LAZY SCROLL
# ==========================================
def make_driver(headless=HEADLESS):
    if not os.path.exists(EDGE_DRIVER_PATH):
        raise FileNotFoundError(f"Không tìm thấy WebDriver tại đường dẫn quy định: {EDGE_DRIVER_PATH}")
    service = Service(EDGE_DRIVER_PATH)
    options = webdriver.EdgeOptions()
    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu") 
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0')
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    return webdriver.Edge(service=service, options=options)

def scroll_full_page(driver):
    """Cuộn bám đuôi phần tử card cuối cùng để ép nạp hết các chuyến bay."""
    card_xpath = "//div[@class='css-1dbjc4n r-9nbb9w r-otx420 r-1i1ao36 r-1x4r79x']"
    last_cards_count = 0
    no_change_count = 0
    
    while True:
        current_cards = driver.find_elements(By.XPATH, card_xpath)
        current_count = len(current_cards)
        if current_count == 0:
            time.sleep(1)
            continue
        if current_count == last_cards_count:
            no_change_count += 1
            if no_change_count >= 4: break
        else:
            last_cards_count = current_count
            no_change_count = 0
        try:
            last_card = current_cards[-1]
            driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", last_card)
            time.sleep(1)
        except:
            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(1)
            
    driver.execute_script("window.scrollTo(0, 0);")
    time.sleep(1)

# ==========================================
# 6. CORE CRAWLER LOGIC (XỬ LÝ CHI TIẾT)
# ==========================================
def crawl_one_url(driver, url):
    try:
        driver.get(url)
        time.sleep(6)  
        wait = WebDriverWait(driver, 12)

        # 1. BẤM BỘ LỌC "BAY THẲNG" CHUẨN XPATH TEXT
        try:
            btn_filter = driver.find_element(By.XPATH, "//div[text()='Bay thẳng']/preceding::div[@aria-checked][1]")
            if btn_filter.get_attribute("aria-checked") == "false":
                driver.execute_script("arguments[0].click();", btn_filter)
                time.sleep(4)  
        except:
            pass

        # 2. GỌI HÀM VÉT ĐÁY LIÊN TỤC
        scroll_full_page(driver)

        # 3. ĐẾM TỔNG SỐ VÉ THỰC TẾ TRÊN TOÀN DOM
        card_xpath = "//div[@class='css-1dbjc4n r-9nbb9w r-otx420 r-1i1ao36 r-1x4r79x']"
        total_cards = len(driver.find_elements(By.XPATH, card_xpath))
        
        log.info(f"Link: {url} | Số chuyến bay đã định vị: {total_cards}")
        
        if total_cards == 0:
            return None

        rows = []
        for i in range(total_cards):
            try:
                current_cards = driver.find_elements(By.XPATH, card_xpath)
                if i >= len(current_cards): break
                card = current_cards[i]

                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", card)
                time.sleep(0.3)

                # --- ĐOẠN KIỂM TRA ĐIỀU KIỆN DỪNG (MỚI THÊM) ---
                card_text = card.text.lower()
                if "phổ thông đặc biệt" in card_text or "thương gia" in card_text:
                    log.info(f"--> Gặp hạng vé đặc biệt ('Phổ thông Đặc biệt' hoặc 'Thương gia'). Dừng cào link này tại vị trí card thứ {i+1}!")
                    break
                # -----------------------------------------------

                brand = card.find_element(By.XPATH, ".//div[@class='css-1dbjc4n r-1habvwh r-18u37iz r-1ssbvtb']//div[@dir='auto']").text
                raw_price = card.find_element(By.XPATH, ".//h3[@data-testid='label_fl_inventory_price']").text
                price = raw_price.split('/')[0].strip() if '/' in raw_price else raw_price.strip()

                detail_btn = card.find_element(By.XPATH, ".//*[contains(text(), 'Chi tiết') or contains(text(), 'Flight Detail')]")
                driver.execute_script("arguments[0].click();", detail_btn) 
                
                def get_inner_text(sub_xpath):
                    try: return card.find_element(By.XPATH, sub_xpath).text
                    except: return ""

                try:
                    wait.until(
                        lambda d: len(card.find_elements(
                            By.XPATH,
                            ".//div[@dir='auto' and contains(translate(text(),'KG','kg'),'kg')]"
                        )) > 0
                    )
                except:
                    pass

                bag_els = card.find_elements(
                    By.XPATH,
                    ".//div[@dir='auto']"
                )

                bag_texts = []

                for el in bag_els:
                    txt = el.text.strip()

                    if not txt:
                        continue

                    if "kg" not in txt.lower():
                        continue

                    if txt not in bag_texts:
                        bag_texts.append(txt)

                hand = "Không có"
                checked = "Không có"

                for txt in bag_texts:
                    lower = txt.lower()

                    # Hành lý xách tay
                    if "xách tay" in lower:
                        hand = txt

                    # Hành lý ký gửi
                    elif lower.startswith("hành lý"):
                        checked = txt

                # --- FLIGHT ID ---
                flight_id = "UNKNOWN"
                try:
                    flight_id = card.find_element(By.XPATH, ".//span[@data-element='flightNumber']").text.strip()
                except:
                    pass

                # --- AIRPORTS ---
                take_place = "Không rõ"
                destination = "Không rõ"
                try:
                    # 1. Điểm đi (Take Place)
                    take_place_el = card.find_element(By.XPATH, ".//div[contains(@class,'r-1h0z5md')]//div[contains(text(),'(')]")
                    take_place = take_place_el.text.strip()
                except:
                    pass

                try:
                    # 2. Điểm đến (Destination)
                    destination_el = card.find_element(By.XPATH, ".//div[contains(@class,'r-e8mqni') and contains(@class,'r-q3we1')]//div[contains(text(),'(')]")
                    destination = destination_el.text.strip()
                except:
                    pass

                # --- TRÍCH XUẤT THỜI GIAN ---
                time_elements = card.find_elements(By.XPATH, ".//div[@dir='auto' and contains(text(), ':') and not(contains(text(), 'h'))]")
                start_time, end_time = "Không rõ", "Không rõ"
                if len(time_elements) >= 2:
                    start_time = time_elements[0].text.strip()
                    end_time = time_elements[1].text.strip()

                # --- TRÍCH XUẤT NGÀY THÁNG ---
                day_elements = card.find_elements(By.XPATH, ".//div[@dir='auto' and contains(text(), 'thg')]")
                start_day, end_day = "Không rõ", "Không rõ"
                if len(day_elements) >= 2:
                    start_day = day_elements[0].text.strip()
                    end_day = day_elements[1].text.strip()
                elif len(day_elements) == 1:
                    start_day = day_elements[0].text.strip()
                    end_day = day_elements[0].text.strip()
                    
                trip_time = "Không rõ"
                try:
                    trip_time = get_inner_text(".//div[contains(@class,'r-13awgt0') and contains(@class,'r-fdjqy7')]")
                except:
                    pass

                rows.append({
                    'id': flight_id,
                    'brand': brand,
                    'price': price,
                    'start_time': start_time,
                    'start_day': start_day,
                    'end_time': end_time,
                    'end_day': end_day,
                    'trip_time': trip_time,
                    'take_place': take_place,
                    'destination': destination,
                    'hand_luggage': hand,
                    'checked_baggage': checked,
                    'crawl_date': datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
                })

                try:
                    driver.execute_script("arguments[0].click();", detail_btn)
                except:
                    pass
                time.sleep(CRAWL_DELAY)

            except Exception as e:
                continue

        if not rows: return None
        df_page = pd.DataFrame(rows, columns=COLUMNS)
        
        # --- TỰ ĐỘNG GHI NỐI ĐUÔI VÀO FILE (APPEND MODE) ---
        try:
            raw_dest = df_page['destination'].iloc[0]
            raw_day = df_page['start_day'].iloc[0]
            
            dest_code_match = re.search(r'\(([A-Z]{3})\)', raw_dest)
            dest_code = dest_code_match.group(1) if dest_code_match else "UNKNOWN"
            clean_day = raw_day.replace(' ', '_').replace('/', '_').replace('-', '_')
            
            file_path = DATA_DIR / f"SGN_{dest_code}_{clean_day}.csv"
            file_exists = os.path.exists(file_path)
            
            # Ghi đè tiêu đề nếu file chưa có, nếu có rồi thì chỉ thêm data mới vào cuối file
            df_page.to_csv(file_path, mode='a', index=False, header=not file_exists, encoding='utf-8-sig')
        except Exception as e:
            url_key = url_to_key(url)
            df_page.to_csv(DATA_DIR / f"SGN_UNKNOWN_{url_key}.csv", mode='a', index=False, encoding='utf-8-sig')

        return df_page

    except WebDriverException:
        return None

# ==========================================
# 7. ĐIỀU PHỐI PIPELINE & TIẾN TRÌNH RETRY
# ==========================================
def crawl_with_retry(driver, url, retries=MAX_RETRIES):
    for attempt in range(1, retries + 1):
        result = crawl_one_url(driver, url)
        if result is not None and len(result) > 0:
            return result
        if attempt < retries:
            sleep(RETRY_WAIT * attempt)   
    return None

def run_crawl_pipeline(destinations, days_ahead, specific_date=None, headless=HEADLESS):
    url_list = get_urls(destinations, days_ahead, specific_date)
    
    log.info(f"Khởi chạy Pipeline: Tổng số link mục tiêu cần cào mới: {len(url_list)}")

    driver = make_driver(headless=headless)
    try:
        for url in url_list:
            crawl_with_retry(driver, url)
    finally:
        driver.quit()
            
# ==========================================
# 8. BỘ ĐIỀU KHIỂN DÒNG LỆNH (MAIN COMMAND LINE ARGS)
# ==========================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hệ thống tự động cào vé máy bay Traveloka.")
    
    parser.add_argument('--dest', nargs='+', default=['PQC', 'HAN', 'DAD', 'HPH', 'CXR'])
    parser.add_argument('--days', type=int, default=20)
    parser.add_argument('--date', type=str, default=None)
    parser.add_argument('--gui', action='store_true', default=False)

    args = parser.parse_args()

    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        driver = make_driver(headless=False)
        try:
            test_url = get_urls(["HAN"], days_ahead=1)[0]
            print(f"Mục tiêu test đơn: {test_url}")
            res_df = crawl_one_url(driver, test_url)
        finally: 
            driver.quit()
    else:
        headless_mode = HEADLESS if not args.gui else False
        
        run_crawl_pipeline(
            destinations=args.dest, 
            days_ahead=args.days, 
            specific_date=args.date, 
            headless=headless_mode
        )