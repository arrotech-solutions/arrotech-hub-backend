"""
M-Pesa Parser Service
Parses unstructured M-Pesa data (SMS, Statements) into structured objects.
"""
import re
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
import csv
from io import StringIO

logger = logging.getLogger(__name__)

class MpesaParserService:
    """Service for parsing M-Pesa text and statements."""

    # Regex Patterns for M-Pesa SMS
    # Example: "Confirmed. Ksh1,500.00 sent to PAYMENT SERVICES 111222... on 12/1/25 at 1:30 PM. New M-PESA balance is..."
    # Example: "QG442342 Confirmed. on 12/1/25 at 1:30 PM Ksh1,500.00 received from JOHN DOE 0712345678..."
    
    # Common OCR/Typo confusions to clean
    CLEAN_MAP = {
        'O': '0',
        'I': '1',
        'l': '1',
        'o': '0',
        'S': '5',
        'B': '8'
    }

    def clean_reference(self, reference: str) -> str:
        """
        Clean common typos in reference numbers (e.g., '0' vs 'O').
        M-Pesa transaction IDs are usually 10 chars, starting with 2 letters allowing numbers.
        Reference fields set by users are wild.
        """
        if not reference:
            return ""
        
        # Upper case standardizes
        cleaned = reference.upper()
        
        # If it looks like a TransID (e.g. QG...), strict rules might apply, 
        # but for user-entered references (Account No), we just do basic cleanup.
        return cleaned.strip()

    def parse_sms(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse a single M-Pesa SMS text.
        Returns dictionary with transaction details or None if failed.
        """
        if not text:
            return None

        # pattern for RECEIVED payment (C2B)
        # "SE54RT32 Confirmed. On 28/4/23 at 5:30 PM Ksh1,500.00 received from JOHN DOE 0712345678. New M-PESA Balance is..."
        # Regex needs to be robust. 
        # 1. TransID (Start of string usually)
        # 2. Date/Time
        # 3. Amount
        # 4. Sender
        
        try:
            # 1. Extract Transaction ID (First word usually, alphanumeric 10 chars)
            trans_id_match = re.search(r'^([A-Z0-9]{10})\s', text)
            if not trans_id_match:
                return None # Not a standard M-Pesa message start
            
            trans_id = trans_id_match.group(1)

            # 2. Extract Amount (Ksh followed by numbers and commas)
            # Handle "Ksh1,500.00" or "Ksh 1500"
            amount_match = re.search(r'Ksh\s?([\d,]+\.\d{2})', text, re.IGNORECASE)
            if not amount_match:
                # Try without decimal
                amount_match = re.search(r'Ksh\s?([\d,]+)', text, re.IGNORECASE)
            
            amount_str = amount_match.group(1).replace(',', '') if amount_match else "0.00"
            amount = float(amount_str)

            # 3. Extract Sender details (from ... )
            # "received from JOHN DOE 0712345678"
            sender_match = re.search(r'received from\s+(.*?)\s+(\d{10,12})', text, re.IGNORECASE)
            
            sender_name = "Unknown"
            sender_phone = ""
            
            if sender_match:
                sender_name = sender_match.group(1)
                sender_phone = sender_match.group(2)
            
            # 4. Extract Date/Time
            # "On 28/4/23 at 5:30 PM"
            date_match = re.search(r'On\s+(\d{1,2}/\d{1,2}/\d{2,4})\s+at\s+(\d{1,2}:\d{2}\s?[AP]M)', text, re.IGNORECASE)
            
            timestamp = datetime.utcnow() # Fallback
            if date_match:
                date_str = date_match.group(1)
                time_str = date_match.group(2)
                # Parse naive string
                try:
                    timestamp = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%y %I:%M %p")
                except ValueError:
                    try:
                        timestamp = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %I:%M %p")
                    except:
                        pass # Keep UTC now
            
            return {
                "transaction_id": trans_id,
                "amount": amount,
                "sender_name": sender_name,
                "phone_number": sender_phone,
                "transaction_time": timestamp,
                "type": "C2B", # Assumed based on 'received from'
                "original_text": text
            }

        except Exception as e:
            logger.error(f"Error parsing SMS: {e}")
            return None

    def parse_statement_csv(self, csv_content: str) -> List[Dict[str, Any]]:
        """
        Parse a CSV export of an M-Pesa Statement.
        Expected columns: Receipt No, Completion Time, Details, Transaction Status, Paid In, Withdrawn, Balance
        """
        transactions = []
        try:
            f = StringIO(csv_content)
            reader = csv.DictReader(f)
            
            for row in reader:
                # Map columns flexibly
                trans_id = row.get("Receipt No.") or row.get("Receipt No")
                if not trans_id:
                    continue
                
                # Filter specific rows?
                
                paid_in = row.get("Paid In") or "0"
                if not paid_in or float(paid_in.replace(',','')) == 0:
                    continue # Skip outflows for reconciliation? Or distinct them?
                    
                amount = float(paid_in.replace(',',''))
                details = row.get("Details") or ""
                
                # Parse details for Sender/Phone
                # Format: "Payment received from 2547... - Name"
                phone = ""
                name = details
                
                phone_match = re.search(r'(254\d{9})', details)
                if phone_match:
                    phone = phone_match.group(1)
                    # Name is usually after phone
                    # details.split(phone)[1]...
                
                timestamp_str = row.get("Completion Time") or ""
                # Parse timestamp...
                
                transactions.append({
                    "transaction_id": trans_id,
                    "amount": amount,
                    "description": details,
                    "phone_number": phone,
                    "transaction_time": timestamp_str, # Needs parsing
                    "status": row.get("Transaction Status")
                })
                
        except Exception as e:
            logger.error(f"Error parsing CSV: {e}")
            
        return transactions

    def batch_process(self, texts: List[str]) -> List[Dict[str, Any]]:
        """Process a list of SMS texts."""
        results = []
        for text in texts:
            res = self.parse_sms(text)
            if res:
                results.append(res)
        return results
