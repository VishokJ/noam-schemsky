#!/usr/bin/env python3

import warnings
warnings.filterwarnings("ignore")

import re
import os
from typing import List, Dict, Any
from pathlib import Path
from openai import OpenAI
from pydantic import BaseModel
from .hyperparams import get as H

class DesignRule(BaseModel):
    rule: str
    category: str
    essential: bool

class RulesResponse(BaseModel):
    rules: List[DesignRule]

OPENAI_API_KEY = "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"

def extract_comprehensive_rules_from_datasheet(file_path: Path, pin_table: List[List[str]]) -> List[Dict[str, Any]]:
    """Extract comprehensive design rules using LLM analysis of full datasheet content."""
    
    try:
        import pdfplumber
        
        # Extract all relevant text from the datasheet
        all_content_sections = []
        
        with pdfplumber.open(file_path) as pdf:
            print(f"Processing {len(pdf.pages)} pages for comprehensive rule extraction...")
            
            # Extract text from all pages
            for page_num, page in enumerate(pdf.pages):
                try:
                    text = page.extract_text() or ""
                    if text.strip():
                        # Clean and prepare text
                        cleaned_text = clean_text(text)
                        if len(cleaned_text) > 100:  # Only substantial content
                            all_content_sections.append({
                                "page": page_num + 1,
                                "content": cleaned_text[:4000]  # Limit per page for token management
                            })
                except Exception as e:
                    print(f"Error processing page {page_num + 1}: {e}")
                    continue
        
        if not all_content_sections:
            print("No content extracted from PDF")
            return []
        
        # Extract pin information for context
        pin_context = extract_pin_context(pin_table)
        
        # Process content in batches to stay within token limits
        all_rules = []
        batch_size = 10  # Process 10 pages at a time
        
        for i in range(0, len(all_content_sections), batch_size):
            batch = all_content_sections[i:i+batch_size]
            batch_rules = extract_rules_from_content_batch(batch, pin_context, file_path.stem)
            all_rules.extend(batch_rules)
            print(f"Processed pages {i+1}-{min(i+batch_size, len(all_content_sections))}, found {len(batch_rules)} rules")
        
        # Remove duplicates while preserving order
        unique_rules = remove_duplicate_rules(all_rules)
        print(f"Total unique rules extracted: {len(unique_rules)}")
        
        return unique_rules
        
    except Exception as e:
        print(f"Error in comprehensive rule extraction: {e}")
        return []

def clean_text(text: str) -> str:
    """Clean and normalize text for LLM processing."""
    if not text:
        return ""
    
    # Remove excessive whitespace and normalize
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[\t\n\r]+', ' ', text)
    
    # Remove page headers/footers and common noise
    text = re.sub(r'DocID\d+.*?Rev\s+\d+', '', text)
    text = re.sub(r'\d+/\d+', '', text)  # Page numbers
    
    return text.strip()

def extract_pin_context(pin_table: List[List[str]]) -> str:
    """Extract pin information to provide context for rule extraction."""
    if not pin_table or len(pin_table) < 2:
        return "No pin table available."
    
    pin_info = []
    headers = pin_table[0] if pin_table else []
    
    for row in pin_table[1:]:
        if len(row) >= 2:
            pin_num = row[0].strip()
            pin_name = row[1].strip()
            pin_type = row[2].strip() if len(row) > 2 else ""
            pin_desc = row[3].strip() if len(row) > 3 else ""
            
            pin_info.append(f"Pin {pin_num}: {pin_name} ({pin_type}) - {pin_desc}")
    
    return f"Device pins:\\n" + "\\n".join(pin_info[:15])  # Limit to first 15 pins

def extract_rules_from_content_batch(content_sections: List[Dict], pin_context: str, device_name: str) -> List[Dict[str, Any]]:
    """Extract design rules from a batch of content using LLM."""
    
    # Combine content from the batch
    combined_content = ""
    page_refs = []
    
    for section in content_sections:
        combined_content += f"\\n\\n--- Page {section['page']} ---\\n{section['content']}"
        page_refs.append(str(section['page']))
    
    # Truncate if too long
    if len(combined_content) > 12000:
        combined_content = combined_content[:12000] + "\\n[Content truncated...]"
    
    prompt = f"""You are an expert hardware design engineer analyzing a semiconductor datasheet for {device_name}.

Extract ALL hardware design rules that can be verified by examining the schematic, netlist, and BOM. Focus on:

INCLUDE these types of rules:
• Power supply voltage ranges and current requirements
• Pin connection requirements (pull-up/pull-down resistors with specific values)
• Component requirements (capacitor values, resistor values, crystal specifications)
• Electrical interface requirements (I2C, SPI, UART connection rules)
• Grounding and power plane requirements  
• ESD protection requirements
• Component placement requirements (decoupling capacitors, etc.)
• Signal integrity requirements (impedance, trace length, etc.)

EXCLUDE these types of rules:
• Software configuration, API calls, register programming
• Timing specifications (setup/hold times, clock requirements)
• Operating modes and measurement settings
• Calibration procedures and algorithms
• Threshold settings and filtering parameters

For each rule:
- Make it specific and actionable
- Include exact component values when specified
- Make it verifiable from hardware design files only
- Mark as "essential" if the circuit won't function without it, "false" if it's a recommendation

{pin_context}

DATASHEET CONTENT (Pages {', '.join(page_refs)}):
{combined_content}

Extract comprehensive hardware design rules from this content."""

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        completion = client.beta.chat.completions.parse(
            model="gpt-4o",  # Use gpt-4o for reliability
            messages=[
                {"role": "system", "content": "You are an expert hardware design engineer extracting design rules from semiconductor datasheets."},
                {"role": "user", "content": prompt}
            ],
            response_format=RulesResponse,
            max_completion_tokens=4000
        )
        
        if completion.choices[0].message.parsed:
            rules_response = completion.choices[0].message.parsed
            return [
                {
                    "rule": rule.rule,
                    "category": rule.category,
                    "essential": rule.essential
                }
                for rule in rules_response.rules
            ]
        else:
            print("Failed to parse structured response")
            return []
            
    except Exception as e:
        print(f"Error in LLM rule extraction: {e}")
        return []

def remove_duplicate_rules(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate rules while preserving order."""
    seen_rules = set()
    unique_rules = []
    
    for rule in rules:
        rule_text = rule["rule"].lower().strip()
        if rule_text not in seen_rules:
            seen_rules.add(rule_text)
            unique_rules.append(rule)
    
    return unique_rules

def extract_rules_for_html(file_path: Path, pin_table: List[List[str]]) -> List[Dict[str, Any]]:
    """Extract rules from HTML file using LLM."""
    try:
        html = file_path.read_text(encoding="utf-8", errors="ignore")
        # Convert HTML to text for LLM processing
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        text_content = soup.get_text()
        
        # Clean and process like PDF content
        cleaned_content = clean_text(text_content)
        pin_context = extract_pin_context(pin_table)
        
        # Process as single batch
        content_sections = [{"page": 1, "content": cleaned_content[:12000]}]
        return extract_rules_from_content_batch(content_sections, pin_context, file_path.stem)
        
    except Exception as e:
        print(f"Error processing HTML file: {e}")
        return []

def extract_rules_for_pdf(file_path: Path, pin_table: List[List[str]]) -> List[Dict[str, Any]]:
    """Extract rules from PDF file using comprehensive LLM analysis."""
    return extract_comprehensive_rules_from_datasheet(file_path, pin_table)