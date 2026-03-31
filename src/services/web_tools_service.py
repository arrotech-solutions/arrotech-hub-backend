"""
Web Tools Service for web scraping, link generation, and web automation.
"""

import asyncio
import json
import logging
import re
import time
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin, urlparse

import aiohttp
import shortuuid
from bs4 import BeautifulSoup

from ..config import settings

# Try to import Selenium, but make it optional
try:
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException, WebDriverException
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("Warning: Selenium not available. Advanced web scraping features will be disabled.")

try:
    from duckduckgo_search import DDGS
    DDG_AVAILABLE = True
except ImportError:
    DDG_AVAILABLE = False
    print("Warning: duckduckgo-search not available. Live web search will be disabled.")

logger = logging.getLogger(__name__)


class WebToolsService:
    """Production-ready service for web scraping, link generation, and web automation."""
    
    def __init__(self):
        self.session = None
        self.driver = None
        self.link_cache = {}
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0'
        ]
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with robust headers."""
        if self.session is None or self.session.closed:
            headers = {
                'User-Agent': self.user_agents[0],
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'max-age=0'
            }
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers=headers
            )
        return self.session
    
    async def _get_selenium_driver(self):
        """Get or create Selenium WebDriver for JavaScript rendering."""
        if self.driver is None:
            try:
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("--disable-gpu")
                chrome_options.add_argument("--window-size=1920,1080")
                chrome_options.add_argument("--user-agent=" + self.user_agents[0])
                chrome_options.add_argument("--disable-blink-features=AutomationControlled")
                chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
                chrome_options.add_experimental_option('useAutomationExtension', False)
                
                self.driver = webdriver.Chrome(options=chrome_options)
                self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                
            except Exception as e:
                logger.error(f"Failed to initialize Selenium driver: {e}")
                return None
        
        return self.driver
    
    def _is_safe_url(self, url: str) -> bool:
        """Validate URL to prevent Server-Side Request Forgery (SSRF)."""
        import socket
        import ipaddress
        from urllib.parse import urlparse
        
        try:
            parsed = urlparse(url)
            # Only allow HTTP/HTTPS, block file://, ftp:// etc.
            if parsed.scheme not in ('http', 'https'):
                logger.warning(f"SSRF blocked: Invalid scheme {parsed.scheme}")
                return False
                
            hostname = parsed.hostname
            if not hostname:
                return False
                
            # Prevent simple localhost bypasses
            if hostname.lower() in ('localhost', '127.0.0.1', '0.0.0.0', '[::1]'):
                logger.warning(f"SSRF blocked: localhost request")
                return False
                
            # Resolve the hostname to an IP to check if it points internally
            ip_addr = socket.gethostbyname(hostname)
            ip = ipaddress.ip_address(ip_addr)
            
            # Check if it's a private, loopback, link-local, or multicast address
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                logger.warning(f"SSRF blocked: Private IP address {ip}")
                return False
                
            # Explicitly block AWS/GCP/Azure instance metadata endpoints
            if str(ip) == "169.254.169.254":
                logger.warning(f"SSRF blocked: Cloud metadata service request")
                return False
                
            return True
        except socket.gaierror:
            # Domain could not be resolved
            return False
        except Exception as e:
            logger.warning(f"URL validation failed for {url}: {e}")
            return False

    async def scrape_website_robust(self, url: str, use_selenium: bool = True) -> Dict[str, Any]:
        """Production-ready website scraping with multiple strategies."""
        try:
            # Prevent Server-Side Request Forgery (SSRF) BEFORE making any HTTP request
            if not self._is_safe_url(url):
                return {"success": False, "error": f"URL {url} is not allowed or could not be resolved (SSRF protection activated)"}
                
            logger.info(f"Starting robust scraping of: {url}")
            
            # Strategy 1: Try basic HTTP scraping first
            basic_result = await self._scrape_basic_http(url)
            
            # Strategy 2: If basic scraping fails or returns minimal data, try Selenium
            if use_selenium and SELENIUM_AVAILABLE:
                selenium_result = await self._scrape_with_selenium(url)
                
                # Combine results, preferring Selenium for JavaScript-heavy sites
                if selenium_result["success"]:
                    combined_data = self._combine_scraping_results(basic_result, selenium_result)
                    return combined_data
            
            # Strategy 3: Enhanced parsing of basic result
            enhanced_result = await self._enhance_basic_scraping(basic_result)
            
            return enhanced_result
            
        except Exception as e:
            logger.error(f"Error in robust scraping of {url}: {e}")
            return {"success": False, "error": str(e)}
    
    async def _scrape_basic_http(self, url: str) -> Dict[str, Any]:
        """Basic HTTP scraping with robust error handling."""
        try:
            session = await self._get_session()
            
            async with session.get(url, allow_redirects=True) as response:
                if response.status != 200:
                    return {"success": False, "error": f"HTTP {response.status}"}
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract comprehensive data
                data = self._extract_comprehensive_data(soup, url)
                
                return {
                    "success": True,
                    "url": url,
                    "data": data,
                    "method": "http",
                    "timestamp": time.time()
                }
                
        except Exception as e:
            logger.error(f"Error in basic HTTP scraping: {e}")
            return {"success": False, "error": str(e)}
    
    async def _scrape_with_selenium(self, url: str) -> Dict[str, Any]:
        """Selenium-based scraping for JavaScript-heavy sites."""
        try:
            driver = await self._get_selenium_driver()
            if not driver:
                return {"success": False, "error": "Selenium driver not available"}
            
            # Navigate to URL
            driver.get(url)
            
            # Wait for page to load
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: d.execute_script("return document.readyState") == "complete"
                )
            except TimeoutException:
                logger.warning("Page load timeout, continuing with current state")
            
            # Additional wait for dynamic content
            await asyncio.sleep(2)
            
            # Get page source
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract comprehensive data
            data = self._extract_comprehensive_data(soup, url)
            
            # Take screenshot for debugging
            screenshot = None
            try:
                screenshot = driver.get_screenshot_as_base64()
            except:
                pass
            
            return {
                "success": True,
                "url": url,
                "data": data,
                "method": "selenium",
                "screenshot": screenshot,
                "timestamp": time.time()
            }
            
        except Exception as e:
            logger.error(f"Error in Selenium scraping: {e}")
            return {"success": False, "error": str(e)}
    
    def _extract_comprehensive_data(self, soup: BeautifulSoup, url: str) -> Dict[str, Any]:
        """Extract comprehensive data from BeautifulSoup object."""
        data = {}
        
        # Basic page info
        data["title"] = soup.find('title').get_text(strip=True) if soup.find('title') else ""
        
        # Meta tags
        data["meta_tags"] = self._extract_meta_tags(soup)
        
        # Headings
        data["headings"] = self._extract_headings(soup)
        
        # Links
        data["links"] = self._extract_links(soup, url)
        
        # Images
        data["images"] = self._extract_images(soup, url)
        
        # Text content
        data["text_content"] = self._extract_text_content(soup)
        
        # Structured data
        data["structured_data"] = self._extract_structured_data(soup)
        
        # Forms
        data["forms"] = self._extract_forms(soup, url)
        
        # Tables
        data["tables"] = self._extract_tables(soup)
        
        # Lists
        data["lists"] = self._extract_lists(soup)
        
        # Buttons and interactive elements
        data["buttons"] = self._extract_buttons(soup)
        
        # Scripts and styles
        data["scripts"] = self._extract_scripts(soup)
        data["styles"] = self._extract_styles(soup)
        
        return data
    
    def _extract_meta_tags(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract all meta tags."""
        meta_tags = {}
        
        for meta in soup.find_all('meta'):
            name = meta.get('name') or meta.get('property') or meta.get('http-equiv')
            content = meta.get('content')
            if name and content:
                meta_tags[name] = content
        
        return meta_tags
    
    def _extract_headings(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Extract all headings with their levels."""
        headings = []
        
        for tag_name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            for heading in soup.find_all(tag_name):
                text = heading.get_text(strip=True)
                if text:
                    headings.append({
                        "level": int(tag_name[1]),
                        "text": text,
                        "id": heading.get('id', ''),
                        "class": ' '.join(heading.get('class', []))
                    })
        
        return headings
    
    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Extract all links with comprehensive information."""
        links = []
        
        for link in soup.find_all('a', href=True):
            href = link.get('href')
            text = link.get_text(strip=True)
            
            if href and text:
                # Resolve relative URLs
                full_url = urljoin(base_url, href)
                
                links.append({
                    "text": text,
                    "href": href,
                    "full_url": full_url,
                    "title": link.get('title', ''),
                    "target": link.get('target', ''),
                    "rel": link.get('rel', []),
                    "class": ' '.join(link.get('class', []))
                })
        
        return links
    
    def _extract_images(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        """Extract all images with comprehensive information."""
        images = []
        
        for img in soup.find_all('img'):
            src = img.get('src')
            if src:
                full_src = urljoin(base_url, src)
                
                images.append({
                    "src": src,
                    "full_src": full_src,
                    "alt": img.get('alt', ''),
                    "title": img.get('title', ''),
                    "width": img.get('width', ''),
                    "height": img.get('height', ''),
                    "class": ' '.join(img.get('class', []))
                })
        
        return images
    
    def _extract_text_content(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract comprehensive text content."""
        try:
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Get all text
            all_text = soup.get_text()
            
            # Process text into meaningful chunks
            lines = (line.strip() for line in all_text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text_chunks = [chunk for chunk in chunks if chunk and len(chunk) > 10]
            
            # Extract paragraphs
            paragraphs = []
            for p in soup.find_all('p'):
                text = p.get_text(strip=True)
                if text and len(text) > 20:
                    paragraphs.append(text)
            
            # Extract spans and divs with substantial content
            content_elements = []
            for tag_name in ['span', 'div']:
                for tag in soup.find_all(tag_name):
                    text = tag.get_text(strip=True)
                    if text and len(text) > 30:
                        content_elements.append({
                            "tag": tag.name,
                            "text": text,
                            "class": ' '.join(tag.get('class', []))
                        })
            
            return {
                "all_text": all_text,
                "text_chunks": text_chunks[:50],  # Limit to first 50 chunks
                "paragraphs": paragraphs,
                "content_elements": content_elements[:20]  # Limit to first 20 elements
            }
        except Exception as e:
            print(f"❌ Error in _extract_text_content: {e}")
            return {
                "all_text": "",
                "text_chunks": [],
                "paragraphs": [],
                "content_elements": []
            }
    
    def _extract_structured_data(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract structured data (JSON-LD, microdata, etc.)."""
        structured_data = {
            "json_ld": [],
            "microdata": [],
            "opengraph": {},
            "twitter_cards": {},
            "schema_org": []
        }
        
        # JSON-LD
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                structured_data["json_ld"].append(data)
            except:
                pass
        
        # Open Graph
        for meta in soup.find_all('meta', property=re.compile(r'^og:')):
            property_name = meta.get('property', '').replace('og:', '')
            structured_data["opengraph"][property_name] = meta.get('content', '')
        
        # Twitter Cards
        for meta in soup.find_all('meta', attrs={'name': re.compile(r'^twitter:')}):
            property_name = meta.get('name', '').replace('twitter:', '')
            structured_data["twitter_cards"][property_name] = meta.get('content', '')
        
        # Microdata
        for element in soup.find_all(attrs={"itemtype": True}):
            item = {
                "@type": element.get("itemtype"),
                "properties": {}
            }
            
            for prop in element.find_all(attrs={"itemprop": True}):
                prop_name = prop.get("itemprop")
                if prop.get("itemtype"):
                    item["properties"][prop_name] = prop.get("itemtype")
                else:
                    item["properties"][prop_name] = prop.get_text(strip=True)
            
            structured_data["microdata"].append(item)
        
        return structured_data
    
    def _extract_forms(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
        """Extract form information."""
        forms = []
        
        for form in soup.find_all('form'):
            form_data = {
                "action": urljoin(base_url, form.get('action', '')),
                "method": form.get('method', 'get'),
                "id": form.get('id', ''),
                "class": ' '.join(form.get('class', [])),
                "inputs": []
            }
            
            for input_tag in form.find_all('input'):
                input_data = {
                    "type": input_tag.get('type', 'text'),
                    "name": input_tag.get('name', ''),
                    "id": input_tag.get('id', ''),
                    "placeholder": input_tag.get('placeholder', ''),
                    "required": input_tag.get('required') is not None
                }
                form_data["inputs"].append(input_data)
            
            forms.append(form_data)
        
        return forms
    
    def _extract_tables(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract table information."""
        tables = []
        
        for table in soup.find_all('table'):
            table_data = {
                "headers": [],
                "rows": [],
                "class": ' '.join(table.get('class', []))
            }
            
            # Extract headers
            for th in table.find_all('th'):
                table_data["headers"].append(th.get_text(strip=True))
            
            # Extract rows
            for tr in table.find_all('tr'):
                row = []
                for cell_type in ['td', 'th']:
                    for td in tr.find_all(cell_type):
                        row.append(td.get_text(strip=True))
                if row:
                    table_data["rows"].append(row)
            
            tables.append(table_data)
        
        return tables
    
    def _extract_lists(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract list information."""
        lists = []
        
        for list_type in ['ul', 'ol']:
            for list_tag in soup.find_all(list_type):
                list_data = {
                    "type": list_tag.name,
                    "items": [],
                    "class": ' '.join(list_tag.get('class', []))
                }
                
                for li in list_tag.find_all('li'):
                    list_data["items"].append(li.get_text(strip=True))
                
                lists.append(list_data)
        
        return lists
    
    def _extract_buttons(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Extract button information."""
        try:
            buttons = []
            
            # Extract buttons
            for button in soup.find_all('button'):
                button_data = {
                    "text": button.get_text(strip=True) or button.get('value', ''),
                    "type": button.get('type', 'button'),
                    "id": button.get('id', ''),
                    "class": ' '.join(button.get('class', []))
                }
                buttons.append(button_data)
            
            # Extract input buttons
            for input_tag in soup.find_all('input'):
                if input_tag.get('type') in ['button', 'submit', 'reset']:
                    button_data = {
                        "text": input_tag.get('value', ''),
                        "type": input_tag.get('type', 'button'),
                        "id": input_tag.get('id', ''),
                        "class": ' '.join(input_tag.get('class', []))
                    }
                    buttons.append(button_data)
            
            return buttons
        except Exception as e:
            print(f"❌ Error in _extract_buttons: {e}")
            return []
    
    def _extract_scripts(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Extract script information."""
        scripts = []
        
        for script in soup.find_all('script'):
            script_data = {
                "src": script.get('src', ''),
                "type": script.get('type', ''),
                "id": script.get('id', ''),
                "class": ' '.join(script.get('class', []))
            }
            scripts.append(script_data)
        
        return scripts
    
    def _extract_styles(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
        """Extract style information."""
        styles = []
        
        # Extract external stylesheets
        for link in soup.find_all('link'):
            if link.get('rel') == ['stylesheet']:
                styles.append({
                    "type": "external",
                    "href": link.get('href', ''),
                    "media": link.get('media', '')
                })
        
        # Extract inline styles
        for style in soup.find_all('style'):
            styles.append({
                "type": "inline",
                "content_length": len(style.string or '')
            })
        
        return styles
    
    def _combine_scraping_results(self, basic_result: Dict[str, Any], selenium_result: Dict[str, Any]) -> Dict[str, Any]:
        """Combine results from different scraping methods."""
        if not basic_result["success"]:
            return selenium_result
        
        if not selenium_result["success"]:
            return basic_result
        
        # Combine data, preferring Selenium for dynamic content
        combined_data = selenium_result["data"].copy()
        
        # Add any unique data from basic scraping
        basic_data = basic_result["data"]
        for key in basic_data:
            if key not in combined_data or not combined_data[key]:
                combined_data[key] = basic_data[key]
        
        return {
            "success": True,
            "url": selenium_result["url"],
            "data": combined_data,
            "method": "combined",
            "timestamp": time.time()
        }
    
    async def _enhance_basic_scraping(self, basic_result: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance basic scraping results with additional processing."""
        if not basic_result["success"]:
            return basic_result
        
        # Add summary statistics
        data = basic_result["data"]
        summary = {
            "total_headings": len(data.get("headings", [])),
            "total_links": len(data.get("links", [])),
            "total_images": len(data.get("images", [])),
            "total_forms": len(data.get("forms", [])),
            "total_tables": len(data.get("tables", [])),
            "total_lists": len(data.get("lists", [])),
            "total_buttons": len(data.get("buttons", [])),
            "total_scripts": len(data.get("scripts", [])),
            "total_styles": len(data.get("styles", [])),
            "has_meta_description": "description" in data.get("meta_tags", {}),
            "has_og_tags": bool(data.get("structured_data", {}).get("opengraph")),
            "has_twitter_tags": bool(data.get("structured_data", {}).get("twitter_cards")),
            "has_structured_data": bool(data.get("structured_data", {}).get("json_ld"))
        }
        
        basic_result["summary"] = summary
        return basic_result
    
    async def scrape_website(self, url: str, selectors: Dict[str, str] = None) -> Dict[str, Any]:
        """Enhanced website scraping with robust fallback strategies."""
        return await self.scrape_website_robust(url, use_selenium=True)
    
    async def scrape_website_comprehensive(self, url: str) -> Dict[str, Any]:
        """Comprehensive website scraping with multiple approaches."""
        return await self.scrape_website_robust(url, use_selenium=True)
    
    async def extract_structured_data(self, url: str) -> Dict[str, Any]:
        """Extract structured data (JSON-LD, microdata) from a website."""
        try:
            # Prevent Server-Side Request Forgery (SSRF)
            if not self._is_safe_url(url):
                return {"success": False, "error": f"URL {url} is not allowed (SSRF protection activated)"}
                
            session = await self._get_session()
            
            async with session.get(url) as response:
                if response.status != 200:
                    return {"success": False, "error": f"HTTP {response.status}"}
                
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                structured_data = {
                    "json_ld": [],
                    "microdata": [],
                    "opengraph": {},
                    "twitter_cards": {}
                }
                
                # Extract JSON-LD
                json_ld_scripts = soup.find_all('script', type='application/ld+json')
                for script in json_ld_scripts:
                    try:
                        import json
                        data = json.loads(script.string)
                        structured_data["json_ld"].append(data)
                    except:
                        pass
                
                # Extract microdata
                microdata_elements = soup.find_all(attrs={"itemtype": True})
                for element in microdata_elements:
                    item = {}
                    item["@type"] = element.get("itemtype")
                    item["properties"] = {}
                    
                    for prop in element.find_all(attrs={"itemprop": True}):
                        prop_name = prop.get("itemprop")
                        if prop.get("itemtype"):
                            item["properties"][prop_name] = prop.get("itemtype")
                        else:
                            item["properties"][prop_name] = prop.get_text(strip=True)
                    
                    structured_data["microdata"].append(item)
                
                # Extract Open Graph
                og_tags = soup.find_all('meta', property=re.compile(r'^og:'))
                for tag in og_tags:
                    property_name = tag.get('property', '').replace('og:', '')
                    structured_data["opengraph"][property_name] = tag.get('content', '')
                
                # Extract Twitter Cards
                twitter_tags = soup.find_all('meta', attrs={'name': re.compile(r'^twitter:')})
                for tag in twitter_tags:
                    property_name = tag.get('name', '').replace('twitter:', '')
                    structured_data["twitter_cards"][property_name] = tag.get('content', '')
                
                return {
                    "success": True,
                    "url": url,
                    "structured_data": structured_data
                }
        except Exception as e:
            logger.error(f"Error extracting structured data from {url}: {e}")
            return {"success": False, "error": str(e)}
    
    async def generate_short_link(self, original_url: str, custom_alias: str = None) -> Dict[str, Any]:
        """Generate a short link for the given URL."""
        try:
            # Validate URL
            parsed = urlparse(original_url)
            if not parsed.scheme:
                original_url = f"https://{original_url}"
            
            # Generate short ID
            if custom_alias:
                short_id = custom_alias
            else:
                short_id = shortuuid.uuid()[:8]
            
            # Store in cache (in production, this would be in a database)
            self.link_cache[short_id] = {
                "original_url": original_url,
                "created_at": asyncio.get_event_loop().time(),
                "clicks": 0
            }
            
            # Generate short URL (in production, this would be your domain)
            short_url = f"https://mini-hub.link/{short_id}"
            
            return {
                "success": True,
                "original_url": original_url,
                "short_url": short_url,
                "short_id": short_id
            }
        except Exception as e:
            logger.error(f"Error generating short link: {e}")
            return {"success": False, "error": str(e)}
    
    async def generate_tracking_link(self, original_url: str, campaign: str = None, source: str = None) -> Dict[str, Any]:
        """Generate a tracking link with UTM parameters."""
        try:
            # Validate URL
            parsed = urlparse(original_url)
            if not parsed.scheme:
                original_url = f"https://{original_url}"
            
            # Build tracking URL
            tracking_params = {
                "utm_source": source or "mini-hub",
                "utm_medium": "link",
                "utm_campaign": campaign or "general"
            }
            
            # Add parameters to URL
            separator = "&" if "?" in original_url else "?"
            tracking_url = original_url + separator + urllib.parse.urlencode(tracking_params)
            
            return {
                "success": True,
                "original_url": original_url,
                "tracking_url": tracking_url,
                "campaign": campaign,
                "source": source
            }
        except Exception as e:
            logger.error(f"Error generating tracking link: {e}")
            return {"success": False, "error": str(e)}
    
    async def generate_qr_code_link(self, url: str, size: int = 10) -> Dict[str, Any]:
        """Generate QR code for a URL."""
        try:
            from .file_management_service import file_management_service

            # Validate URL
            parsed = urlparse(url)
            if not parsed.scheme:
                url = f"https://{url}"
            
            # Generate QR code
            qr_result = await file_management_service.generate_qr_code(url, size)
            
            if qr_result["success"]:
                return {
                    "success": True,
                    "url": url,
                    "qr_code": qr_result["content"],
                    "size": qr_result["size"]
                }
            else:
                return {"success": False, "error": qr_result["error"]}
        except Exception as e:
            logger.error(f"Error generating QR code link: {e}")
            return {"success": False, "error": str(e)}
    
    async def automate_web_task(self, task_config: Dict[str, Any]) -> Dict[str, Any]:
        """Automate web tasks using Selenium."""
        if not SELENIUM_AVAILABLE:
            return {
                "success": False,
                "error": "Selenium not available. Web automation is disabled."
            }
        
        try:
            target_url = task_config.get("url", "")
            # Prevent Server-Side Request Forgery (SSRF)
            if not target_url or not self._is_safe_url(target_url):
                return {"success": False, "error": f"URL {target_url} is not allowed (SSRF protection activated)"}
                
            # Initialize Chrome driver
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            
            driver = webdriver.Chrome(options=chrome_options)
            
            try:
                # Navigate to URL
                driver.get(task_config["url"])
                
                results = []
                
                # Execute actions
                for action in task_config.get("actions", []):
                    action_type = action.get("type")
                    
                    if action_type == "click":
                        element = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, action["selector"]))
                        )
                        element.click()
                        results.append({"action": "click", "selector": action["selector"], "success": True})
                    
                    elif action_type == "input":
                        element = driver.find_element(By.CSS_SELECTOR, action["selector"])
                        element.clear()
                        element.send_keys(action["value"])
                        results.append({"action": "input", "selector": action["selector"], "success": True})
                    
                    elif action_type == "extract":
                        elements = driver.find_elements(By.CSS_SELECTOR, action["selector"])
                        extracted_data = [elem.text for elem in elements]
                        results.append({
                            "action": "extract",
                            "selector": action["selector"],
                            "data": extracted_data,
                            "success": True
                        })
                    
                    elif action_type == "wait":
                        await asyncio.sleep(action.get("seconds", 1))
                        results.append({"action": "wait", "seconds": action.get("seconds", 1), "success": True})
                
                # Take screenshot if requested
                screenshot = None
                if task_config.get("take_screenshot"):
                    screenshot_path = f"screenshot_{asyncio.get_event_loop().time()}.png"
                    driver.save_screenshot(screenshot_path)
                    with open(screenshot_path, "rb") as f:
                        import base64
                        screenshot = base64.b64encode(f.read()).decode()
                
                return {
                    "success": True,
                    "url": task_config["url"],
                    "results": results,
                    "screenshot": screenshot
                }
            
            finally:
                driver.quit()
        
        except Exception as e:
            logger.error(f"Error automating web task: {e}")
            return {"success": False, "error": str(e)}
    
    async def check_website_status(self, url: str) -> Dict[str, Any]:
        """Check website status and performance."""
        try:
            session = await self._get_session()
            
            start_time = asyncio.get_event_loop().time()
            
            async with session.get(url) as response:
                end_time = asyncio.get_event_loop().time()
                response_time = (end_time - start_time) * 1000  # Convert to milliseconds
                
                return {
                    "success": True,
                    "url": url,
                    "status_code": response.status,
                    "response_time_ms": round(response_time, 2),
                    "headers": dict(response.headers),
                    "is_accessible": response.status == 200
                }
        except Exception as e:
            logger.error(f"Error checking website status: {e}")
            return {"success": False, "error": str(e)}
    
    async def extract_emails_from_website(self, url: str) -> Dict[str, Any]:
        """Extract email addresses from a website."""
        try:
            session = await self._get_session()
            
            async with session.get(url) as response:
                if response.status != 200:
                    return {"success": False, "error": f"HTTP {response.status}"}
                
                html = await response.text()
                
                # Extract emails using regex
                email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
                emails = re.findall(email_pattern, html)
                
                # Remove duplicates and sort
                unique_emails = sorted(list(set(emails)))
                
                return {
                    "success": True,
                    "url": url,
                    "emails": unique_emails,
                    "count": len(unique_emails)
                }
        except Exception as e:
            logger.error(f"Error extracting emails from {url}: {e}")
            return {"success": False, "error": str(e)}
    
    async def perform_web_search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """Perform a live web search using Tavily API (if available) or DuckDuckGo fallback."""
        
        tavily_key = settings.TAVILY_API_KEY
        if tavily_key:
            try:
                # Prioritize Tavily API for highly reliable LLM-optimized search
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "api_key": tavily_key,
                        "query": query,
                        "search_depth": "basic",
                        "include_answer": False,
                        "max_results": max_results
                    }
                    async with session.post("https://api.tavily.com/search", json=payload) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get("results", [])
                            mapped_sources = []
                            for r in results:
                                url = r.get("url", "")
                                domain = ""
                                favicon = None
                                if url:
                                    try:
                                        from urllib.parse import urlparse
                                        domain = urlparse(url).netloc
                                        if domain.startswith("www."):
                                            domain = domain[4:]
                                        favicon = f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
                                    except Exception:
                                        pass
                                        
                                mapped_sources.append({
                                    "title": r.get("title", ""),
                                    "url": url,
                                    "snippet": r.get("content", ""),
                                    "domain": domain,
                                    "favicon": favicon
                                })
                                
                            return {
                                "success": True,
                                "query": query,
                                "max_results": max_results,
                                "sources": mapped_sources,
                                "timestamp": time.time(),
                                "provider": "tavily"
                            }
                        else:
                            error_text = await response.text()
                            logger.error(f"Tavily API returned status {response.status}: {error_text}")
                            # Fall through to DuckDuckGo backup
            except Exception as e:
                logger.error(f"Tavily API call failed, falling back to DuckDuckGo: {e}")
                
        if not DDG_AVAILABLE:
            if tavily_key:
                return {
                    "success": False,
                    "error": "Tavily API search failed and DuckDuckGo is not available."
                }
            return {
                "success": False,
                "error": "duckduckgo-search package is not installed and TAVILY_API_KEY is missing. Live web search is disabled."
            }
            
        try:
            # duckduckgo_search offers sync methods, so we run it in a thread pool
            loop = asyncio.get_event_loop()
            
            def _sync_search():
                results = []
                # Try primary backend (usually 'api')
                try:
                    with DDGS() as ddgs:
                        for r in ddgs.text(query, max_results=max_results):
                            results.append(r)
                except Exception as e:
                    logger.warning(f"DDGS primary backend failed: {e}")
                
                # Fallback 1: Try 'html' backend if primary returned empty or failed
                if not results:
                    try:
                        with DDGS() as ddgs:
                            for r in ddgs.text(query, max_results=max_results, backend='html'):
                                results.append(r)
                    except Exception as e:
                        logger.warning(f"DDGS html backend failed: {e}")
                
                # Fallback 2: Try 'lite' backend
                if not results:
                    try:
                        with DDGS() as ddgs:
                            for r in ddgs.text(query, max_results=max_results, backend='lite'):
                                results.append(r)
                    except Exception as e:
                        logger.warning(f"DDGS lite backend failed: {e}")
                
                mapped_results = []
                for r in results:
                    url = r.get("href", "")
                    domain = ""
                    favicon = None
                    if url:
                        try:
                            from urllib.parse import urlparse
                            domain = urlparse(url).netloc
                            if domain.startswith("www."):
                                domain = domain[4:]
                            favicon = f"https://www.google.com/s2/favicons?domain={domain}&sz=64"
                        except Exception:
                            pass
                            
                    mapped_results.append({
                        "title": r.get("title", ""),
                        "url": url,
                        "snippet": r.get("body", ""),
                        "domain": domain,
                        "favicon": favicon
                    })
                    
                return mapped_results
                
            search_results = await loop.run_in_executor(None, _sync_search)
            
            # If all backends return empty, DuckDuckGo has blocked the datacenter IP
            if not search_results:
                return {
                    "success": False,
                    "error": "Search failed: DuckDuckGo is actively blocking search requests from this server's datacenter IP (Railway/Cloud). For production environments, please integrate a dedicated search API (e.g., Google Custom Search, SERP API, or Tavily)."
                }
            
            return {
                "success": True,
                "query": query,
                "max_results": max_results,
                "sources": search_results,
                "timestamp": time.time()
            }
            
        except Exception as e:
            logger.error(f"Error performing web search for query '{query}': {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def close(self):
        """Close the service and cleanup resources."""
        if self.session and not self.session.closed:
            await self.session.close()
        if self.driver:
            self.driver.quit()


# Global web tools service instance
web_tools_service = WebToolsService()

# Version info for debugging
VERSION = "2.0.0-fixed"
print(f"🌐 WebToolsService initialized - Version: {VERSION}") 