#!/usr/bin/env python3

import warnings
warnings.filterwarnings("ignore")

import re
import os
from typing import List, Dict, Any, Set, Tuple
from pathlib import Path
from openai import OpenAI
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

class DesignRule(BaseModel):
    rule: str
    category: str
    essential: bool

class RulesResponse(BaseModel):
    rules: List[DesignRule]

class GroupedRulesResponse(BaseModel):
    rules: List[DesignRule]

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class PinsResponse(BaseModel):
    pins: List[str]


def normalize_pin_table(pin_table: List[List[str]]) -> Tuple[Set[str], Set[str], Dict[str, str], Dict[str, str]]:
    """Prepare lookup sets and mappings for pin validation.

    Returns:
    - allowed_pin_names: lowercased set of pin names
    - allowed_pin_numbers: lowercased set of pin numbers
    - number_to_name: lowercased pin number -> canonical name
    - name_to_canonical: lowercased pin name -> canonical name
    """
    allowed_pin_names: Set[str] = set()
    allowed_pin_numbers: Set[str] = set()
    number_to_name: Dict[str, str] = {}
    name_to_canonical: Dict[str, str] = {}

    if not pin_table or len(pin_table) < 2:
        print("Warning: No valid pin table found - pin validation will be skipped")
        return allowed_pin_names, allowed_pin_numbers, number_to_name, name_to_canonical

    for row in pin_table[1:]:
        if not row:
            continue
        pin_number = str(row[0]).strip() if len(row) > 0 else ""
        pin_name = str(row[1]).strip() if len(row) > 1 else ""
        if pin_number:
            allowed_pin_numbers.add(pin_number.lower())
        if pin_name:
            allowed_pin_names.add(pin_name.lower())
            name_to_canonical[pin_name.lower()] = pin_name
        if pin_number and pin_name:
            number_to_name[pin_number.lower()] = pin_name

    return allowed_pin_names, allowed_pin_numbers, number_to_name, name_to_canonical


def build_pins_prompt(rule_text: str, pin_table: List[List[str]]) -> str:
    """Construct prompt for selecting associated pins for a rule."""
    lines: List[str] = []
    header = pin_table[0] if pin_table else []
    header_str = ", ".join([str(h).strip() for h in header]) if header else "Pin, Name, Type, Description"
    lines.append(f"Pin table columns: {header_str}")

    # Include the full pin table with all columns
    for row in pin_table[1:]:
        parts = [str(c).strip() for c in row]
        lines.append(" | ".join(parts))

    table_block = "\n".join(lines)
    return (
        "You are an expert hardware design engineer. Given a design rule and the device pin table, "
        "identify ONLY the specific pins from the table that are directly mentioned or electrically involved in the rule.\n\n"
        "IMPORTANT: Be precise and selective - return ONLY pins that are:\n"
        "- Explicitly mentioned by name or number in the rule text\n"
        "- Directly involved in the electrical connections described by the rule\n"
        "- Required for the specific electrical circuit or interface mentioned in the rule\n\n"
        "INCLUDE pins for these scenarios:\n"
        "- Power supply rules: ONLY the specific power pins mentioned (VDD, VCC, VSS, GND, etc.)\n"
        "- Interface rules: ONLY the specific communication pins (SDA/SCL for I2C; MOSI/MISO/SCK for SPI, etc.)\n"
        "- Clock rules: ONLY the specific clock pins mentioned (XTAL, OSC, CLK, etc.)\n"
        "- Analog rules: ONLY the specific analog pins mentioned (AIN, VREF, etc.)\n"
        "- Connection rules: ONLY the pins specifically named in the connection\n\n"
        "EXCLUDE pins for these scenarios:\n"
        "- General mechanical rules (lead length, package mounting, thermal considerations)\n"
        "- General electrical rules that apply to the entire component without mentioning specific pins\n"
        "- Layout rules about trace routing that don't specify particular pins\n"
        "- Assembly or manufacturing rules not related to specific pin connections\n"
        "- Component placement rules that don't involve specific pin connections\n\n"
        "MATCHING RULES:\n"
        "- Match pin names case-insensitively (VDD matches vdd, Vdd, etc.)\n"
        "- Match partial names only if clearly referring to the same pin (VDD matches VDD1, VDD_CORE, etc.)\n"
        "- Map pin numbers to names using the table\n\n"
        "EXAMPLES:\n"
        "- Rule: 'Connect VDD pin to 3.3V supply' → Return: ['VDD'] (if VDD exists in table)\n"
        "- Rule: 'Minimize lead length of TO-220 packages' → Return: [] (general mechanical rule)\n"
        "- Rule: 'Place 100nF capacitor near device' → Return: [] (general placement rule)\n"
        "- Rule: 'Connect SDA and SCL with 4.7kΩ pull-ups' → Return: ['SDA', 'SCL'] (if they exist)\n"
        "- Rule: 'Ensure proper power sequencing' → Return: [] (general rule, no specific pins mentioned)\n\n"
        "Return ONLY pin names from the table's Name column that are specifically relevant to this rule. "
        "If the rule is general and doesn't mention specific pins, return an empty list. "
        "Do not invent pins not present in the table.\n\n"
        f"RULE:\n{rule_text}\n\n"
        f"PIN TABLE:\n{table_block}\n\n"
        "Analyze the rule carefully and return ONLY the specifically relevant pin names."
    )


def select_pins_for_rule(client: OpenAI, rule_text: str, pin_table: List[List[str]]) -> List[str]:
    """Call LLM to select pins for rule and validate against pin table."""
    try:
        prompt = build_pins_prompt(rule_text, pin_table)
        completion = client.beta.chat.completions.parse(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert at mapping design rules to specific pins from device pin tables. Be precise and selective - only include pins that are directly mentioned or electrically involved in the rule."},
                {"role": "user", "content": prompt},
            ],
            response_format=PinsResponse,
            max_completion_tokens=10000,
        )
        parsed = completion.choices[0].message.parsed if completion.choices else None
        model_pins: List[str] = parsed.pins if parsed else []
    except Exception as exc:
        print(f"Error selecting pins: {exc}")
        model_pins = []

    allowed_names, allowed_numbers, number_to_name, name_to_canonical = normalize_pin_table(pin_table)

    normalized: List[str] = []
    seen: Set[str] = set()
    for raw_pin in model_pins:
        candidate = str(raw_pin).strip()
        cl = candidate.lower()
        canonical = ""
        if cl in allowed_names:
            canonical = name_to_canonical.get(cl, candidate)
        elif cl in allowed_numbers:
            mapped = number_to_name.get(cl)
            if mapped:
                canonical = mapped
        if canonical and canonical not in seen:
            seen.add(canonical)
            normalized.append(canonical)
    return normalized

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
                        all_content_sections.append({
                            "page": page_num + 1,
                            "content": cleaned_text
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
            batch_rules = extract_rules_from_content_batch(batch, pin_context, file_path.stem, pin_table)
            all_rules.extend(batch_rules)
            print(f"Processed pages {i+1}-{min(i+batch_size, len(all_content_sections))}, found {len(batch_rules)} rules")
        
        # Remove duplicates while preserving order
        unique_rules = remove_duplicate_rules(all_rules)
        print(f"Total unique rules extracted: {len(unique_rules)}")
        
        # Group and categorize rules for better organization
        if unique_rules:
            grouped_rules = group_and_categorize_rules(unique_rules)
            return grouped_rules
        
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

def extract_rules_from_content_batch(
    content_sections: List[Dict],
    pin_context: str,
    device_name: str,
    pin_table: List[List[str]],
) -> List[Dict[str, Any]]:
    """Extract design rules from a batch of content using LLM."""
    
    # Combine content from the batch
    combined_content = ""
    page_refs = []
    
    for section in content_sections:
        combined_content += f"\\n\\n--- Page {section['page']} ---\\n{section['content']}"
        page_refs.append(str(section['page']))
    
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

CRITICAL: SELF-CONTAINED RULES ONLY - NO DATASHEET REFERENCES:
- NEVER reference tables, sections, pages, or figures (e.g., "as per Table 21", "according to Section 3.4.1", "found in Figure 5")
- NEVER say "refer to datasheet", "see specifications", "per datasheet recommendations"
- ALWAYS extract specific numerical values from tables and include them directly in the rule
- ALWAYS read tables, specifications, and values in the content and state them explicitly
- Rules must be completely self-contained and usable without the original datasheet
- If a table contains values, extract the actual values and put them in the rule text

CRITICAL: PIN NAMING REQUIREMENTS:
- ALWAYS use pin NAMES (like VDD, GND, SDA, SCL, RESET, etc.) in rule text, NEVER pin numbers
- If the datasheet mentions "pin 1, 2, 3", you must look up their corresponding names from the pin table and use those names instead
- Example: Instead of "Connect pins 1, 2, 3, and 4 to the Drain net", write "Connect VDD, VCC, AVDD, and DVDD pins to the Drain net"
- Pin numbers should ONLY be used internally for mapping purposes, never in the final rule text
- Every pin reference in a rule must be by its functional name (VDD, GND, SDA, etc.), not its physical number

EXAMPLE OF GOOD SELF-CONTAINED RULES WITH PROPER PIN NAMING:
• "Connect 32.768 kHz crystal with 18 pF load capacitors between RTC_XTI and RTC_XTO pins with maximum series resistance of 80 kΩ"
• "Supply voltage VDD must be 1.2V ±10% (1.08V to 1.32V)"
• "Place 100 nF decoupling capacitor within 5 mm of each VCC pin"
• "Connect SDA and SCL pins through 4.7 kΩ pull-up resistors to VDD for I2C communication"

EXAMPLE OF BAD RULES WITH PIN NUMBERS:
• "Connect pins 1, 2, 3, and 4 to the Drain net" ❌ (should use pin names instead)
• "Pin 7 is a separate Kelvin Source net" ❌ (should use the pin name instead)
• "Use crystal specifications as defined in Table 21" ❌
• "Follow pin termination recommendations in Section 3.4.1" ❌
• "Refer to datasheet for decoupling requirements" ❌

For each rule:
- Make it specific and actionable with exact values
- Include exact component values, voltages, resistances when specified in the content
- Extract values from any tables or specifications in the content
- Make it verifiable from hardware design files only
- Use ONLY pin names (never pin numbers) when referencing pins
- Mark "essential" as True ONLY if the rule contains keywords like "absolute" or "mandatory", or if the circuit will fail to work without it
- Mark "essential" as False for ALL recommendations, best practices, or optimization guidelines
- Ensure the rule is completely self-contained

{pin_context}

DATASHEET CONTENT (Pages {', '.join(page_refs)}):
{combined_content}

Extract comprehensive hardware design rules from this content. Read all tables and specifications carefully and include specific values directly in the rules."""

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)

        completion = client.beta.chat.completions.parse(
            model="gpt-5",
            messages=[
                {"role": "system", "content": "You are an expert hardware design engineer extracting design rules from semiconductor datasheets."},
                {"role": "user", "content": prompt}
            ],
            response_format=RulesResponse,
            max_completion_tokens=50000
        )
        
        if completion.choices[0].message.parsed:
            rules_response = completion.choices[0].message.parsed
            extracted = [
                {
                    "rule": rule.rule,
                    "category": rule.category,
                    "essential": rule.essential,
                }
                for rule in rules_response.rules
            ]
            # Add pins to each rule
            for r in extracted:
                r_text = str(r.get("rule", "")).strip()
                r["pins"] = select_pins_for_rule(client, r_text, pin_table) if r_text else []
            return extracted
        else:
            print("Failed to parse structured response")
            return []
            
    except Exception as e:
        print(f"Error in LLM rule extraction: {e}")
        return []

def clean_datasheet_references(rule_text: str) -> str:
    """Remove any remaining datasheet references from rule text."""
    # Patterns to remove
    patterns_to_remove = [
        r'\s*as per [Tt]able \d+',
        r'\s*according to [Tt]able \d+',
        r'\s*found in [Tt]able \d+',
        r'\s*defined in [Tt]able \d+',
        r'\s*specified in [Tt]able \d+',
        r'\s*as per [Ss]ection \d+(\.\d+)*',
        r'\s*according to [Ss]ection \d+(\.\d+)*',
        r'\s*found in [Ss]ection \d+(\.\d+)*',
        r'\s*defined in [Ss]ection \d+(\.\d+)*',
        r'\s*specified in [Ss]ection \d+(\.\d+)*',
        r'\s*as per [Ff]igure \d+',
        r'\s*according to [Ff]igure \d+',
        r'\s*found in [Ff]igure \d+',
        r'\s*refer to [Tt]able \d+',
        r'\s*see [Tt]able \d+',
        r'\s*refer to [Ss]ection \d+(\.\d+)*',
        r'\s*see [Ss]ection \d+(\.\d+)*',
        r'\s*refer to [Ff]igure \d+',
        r'\s*see [Ff]igure \d+',
        r'\s*per datasheet recommendations?',
        r'\s*as specified in the datasheet',
        r'\s*according to the datasheet',
        r'\s*refer to the? datasheet',
        r'\s*see the? datasheet',
        r'\s*according to [A-Z][A-Z0-9_]+\s+[a-z][a-z\s]+version\s+[\d\.\w\s]+',
        r'\s*as per [A-Z][A-Z0-9_]+\s+[a-z][a-z\s]+version\s+[\d\.\w\s]+',
        r'\s*following [A-Z][A-Z0-9_]+\s+[a-z][a-z\s]+version\s+[\d\.\w\s]+'
    ]
    
    cleaned_text = rule_text
    for pattern in patterns_to_remove:
        cleaned_text = re.sub(pattern, '', cleaned_text, flags=re.IGNORECASE)
    
    # Clean up any trailing periods or commas that might be left
    cleaned_text = re.sub(r'\s*[,.]?\s*$', '.', cleaned_text)
    cleaned_text = cleaned_text.strip()
    
    return cleaned_text

def remove_duplicate_rules(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate rules while preserving order and cleaning datasheet references."""
    seen_rules = set()
    unique_rules = []
    
    for rule in rules:
        # Clean datasheet references first
        cleaned_rule_text = clean_datasheet_references(rule["rule"])
        
        # Skip rules that are too short after cleaning (likely just references)
        if len(cleaned_rule_text.strip()) < 20:
            continue
            
        rule_text_key = cleaned_rule_text.lower().strip()
        if rule_text_key not in seen_rules:
            seen_rules.add(rule_text_key)
            # Update the rule with cleaned text
            rule["rule"] = cleaned_rule_text
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
        content_sections = [{"page": 1, "content": cleaned_content}]
        rules = extract_rules_from_content_batch(content_sections, pin_context, file_path.stem, pin_table)
        
        # Group and categorize rules
        if rules:
            return group_and_categorize_rules(rules)
        return rules
        
    except Exception as e:
        print(f"Error processing HTML file: {e}")
        return []

def extract_rules_for_pdf(file_path: Path, pin_table: List[List[str]]) -> List[Dict[str, Any]]:
    """Extract rules from PDF file using comprehensive LLM analysis."""
    return extract_comprehensive_rules_from_datasheet(file_path, pin_table)

def build_grouping_prompt(rules: List[Dict[str, Any]]) -> str:
    """Build prompt for grouping and categorizing rules."""
    
    # Format the rules for the prompt
    rules_text = []
    for i, rule in enumerate(rules, 1):
        rule_text = rule.get("rule", "")
        category = rule.get("category", "")
        essential = rule.get("essential", False)
        pins = rule.get("pins", [])
        pins_str = ", ".join(pins) if pins else "None"
        
        rules_text.append(f"""Rule {i}:
Text: {rule_text}
Current Category: {category}
Essential: {essential}
Pins: {pins_str}""")
    
    all_rules_text = "\n\n".join(rules_text)
    
    return f"""You are an expert hardware design engineer. Given a set of design rules extracted from a datasheet, 
reorganize and categorize them to create a cohesive, well-structured ruleset.

CATEGORIZATION GUIDELINES:
- Group similar rules under the same category to reduce redundancy
- Use clear, specific category names without generic words like "Requirements"
- Prefer categories like: "Power Supply Voltage", "Pin Connection", "ESD Protection", 
  "Grounding and Power Plane", "Crystal Oscillator", "Decoupling Capacitors", "Signal Integrity", etc.
- Merge overlapping categories (e.g., "Power Supply" and "Power Requirements" should become "Power Supply")
- Keep essential/non-essential classification unchanged
- Keep pin assignments unchanged
- Keep rule text unchanged

CURRENT RULESET ({len(rules)} rules):

{all_rules_text}

Return the same rules with updated, consolidated categories. Focus on creating 8-12 main categories that logically group the rules."""

def group_and_categorize_rules(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group and categorize rules using LLM to create a cohesive ruleset."""
    
    if not rules:
        return rules
        
    print(f"Grouping and categorizing {len(rules)} rules...")
    
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        prompt = build_grouping_prompt(rules)
        
        completion = client.beta.chat.completions.parse(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": "You are an expert at organizing hardware design rules into logical, cohesive categories."},
                {"role": "user", "content": prompt}
            ],
            response_format=GroupedRulesResponse,
            max_completion_tokens=50000
        )
        
        if completion.choices[0].message.parsed:
            grouped_response = completion.choices[0].message.parsed
            grouped_rules = [
                {
                    "rule": rule.rule,
                    "category": rule.category,
                    "essential": rule.essential,
                    "pins": rules[i].get("pins", [])  # Preserve original pins
                }
                for i, rule in enumerate(grouped_response.rules)
            ]
            
            # Print category summary
            categories = {}
            for rule in grouped_rules:
                cat = rule["category"]
                categories[cat] = categories.get(cat, 0) + 1
            
            print(f"Grouped into {len(categories)} categories:")
            for cat, count in sorted(categories.items()):
                print(f"  - {cat}: {count} rules")
                
            return grouped_rules
        else:
            print("Failed to parse grouped rules response")
            return rules
            
    except Exception as e:
        print(f"Error grouping rules: {e}")
        return rules