#!/usr/bin/env python3

import warnings
import os
warnings.filterwarnings("ignore")
os.environ['PYTHONWARNINGS'] = 'ignore'

from typing import List, Dict, Any
from bs4 import BeautifulSoup
import pdfplumber
from .hyperparams import get as H

def build_html_graph(html: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, 'html.parser')
    nodes: List[Dict[str, Any]] = []
    
    # Extract sections
    for h in soup.find_all(["h1","h2","h3","h4","h5","h6"]):
        title = h.get_text(" ", strip=True)
        block = []
        cur = h
        while cur and len(block) < 10:
            cur = cur.find_next()
            if not cur:
                break
            if cur.name and cur.name.lower() in ["h1","h2","h3","h4","h5","h6"]:
                break
            if cur.name == 'p':
                t = cur.get_text(" ", strip=True)
                if t:
                    block.append(t)
        text = "\n".join(block)
        if text:
            nodes.append({"type":"section","title":title,"text":text})
    
    # Extract tables
    for i, t in enumerate(soup.find_all('table')):
        rows = []
        for tr in t.find_all('tr')[:20]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(['td','th'])]
            if cells:
                rows.append("\t".join(cells))
        if rows:
            nodes.append({"type":"table","title":"table","text":"\n".join(rows)})
    
    return nodes

def build_pdf_graph(pdf_path: str, max_pages: int = None) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    if max_pages is None:
        max_pages = 10  # Simple limit
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = pdf.pages[:max_pages] if max_pages > 0 else pdf.pages
            
            for i, page in enumerate(pages):
                # Simple text extraction
                text = ""
                try:
                    text = page.extract_text() or ""
                except Exception:
                    continue
                
                if text.strip():
                    # Simple section splitting
                    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
                    for j, para in enumerate(paragraphs):
                        if len(para) > 50:  # Only substantial paragraphs
                            nodes.append({
                                "type": "section", 
                                "title": f"Page {i+1} Section {j+1}", 
                                "text": para
                            })
                
                # Simple table extraction
                try:
                    tables = page.extract_tables()
                    for t_idx, table in enumerate(tables or []):
                        if table and len(table) > 1:
                            rows = []
                            for row in table:
                                if row:
                                    cells = [str(cell or "").strip() for cell in row]
                                    if any(cell for cell in cells):
                                        rows.append("\t".join(cells))
                            if rows:
                                nodes.append({
                                    "type": "table",
                                    "title": f"Page {i+1} Table {t_idx+1}",
                                    "text": "\n".join(rows)
                                })
                except Exception:
                    pass
                    
    except Exception:
        pass
    
    return nodes

def chunk_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    for i, n in enumerate(nodes):
        text = n.get('text','')
        if not text:
            continue
        if len(text) < 1500:
            chunks.append({"id":f"n{i}","type":n.get('type',''),"title":n.get('title',''),"text":text})
        else:
            # Simple chunking
            parts = [text[j:j+1200] for j in range(0,len(text),1200)]
            for k,p in enumerate(parts):
                chunks.append({"id":f"n{i}_{k}","type":n.get('type',''),"title":n.get('title',''),"text":p})
    return chunks

def retrieve(chunks: List[Dict[str, Any]], queries: List[str], k: int = None, comprehensive: bool = False) -> List[Dict[str, Any]]:
    if k is None:
        k = 10
    
    scored: List[tuple] = []
    for ch in chunks:
        title = ch.get('title', '').lower()
        text = ch.get('text', '').lower()
        
        score = 0
        for q in queries:
            q_lower = q.lower()
            score += title.count(q_lower) * 2
            score += text.count(q_lower)
        
        # Boost for relevant content
        if any(word in text for word in ['pin', 'signal', 'connection', 'voltage', 'current']):
            score += 5
        
        if score > 0:
            scored.append((score, ch))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:k]]