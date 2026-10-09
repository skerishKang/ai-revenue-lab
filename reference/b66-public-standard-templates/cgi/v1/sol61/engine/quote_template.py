"""Compile a source XLSX + observed PDF into an editable vector quote profile.

The reference PDF is read only at onboarding. Execution uses a blank resource
container, an independently serialized drawing program and source-bound fields.
No reference PDF overlay, raster page, Excel, browser or network is used at run time.
"""
from __future__ import annotations

import argparse
import base64
import copy
from datetime import datetime, timedelta
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
import zlib

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, DecodedStreamObject, NameObject, ByteStringObject, TextStringObject
from font_support import embed_font

HERE = Path(__file__).resolve().parent
DEFAULT_NODE = Path('node')
NS = {'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
      'v':'urn:schemas-microsoft-com:vml', 'excel':'urn:schemas-microsoft-com:office:excel'}


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def native(el, kind):
    """Resolve Hancom mc:AlternateContent before reading native OOXML."""
    if el is None: return None
    return el if el.tag == '{'+NS['x']+'}'+kind else el.find('.//x:'+kind, NS)


def xml_data(el):
    if el is None: return None
    return {'tag':el.tag.rsplit('}',1)[-1], 'attributes':dict(el.attrib),
            'text':el.text, 'children':[xml_data(child) for child in el]}


def workbook_facts(path):
    with zipfile.ZipFile(path) as archive:
        wb=ET.fromstring(archive.read('xl/workbook.xml'))
        sheets=wb.find('x:sheets',NS)
        sheet_name=sheets[0].get('name')
        sheet=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        styles=ET.fromstring(archive.read('xl/styles.xml'))
        strings=[]
        if 'xl/sharedStrings.xml' in archive.namelist():
            ss=ET.fromstring(archive.read('xl/sharedStrings.xml'))
            strings=[''.join(t.text or '' for t in si.findall('.//x:t',NS)) for si in ss]
        fonts=[native(f,'font') for f in styles.find('x:fonts',NS)]
        xfs=[native(f,'xf') for f in styles.find('x:cellXfs',NS)]
        cells={}
        for c in sheet.findall('.//x:sheetData/x:row/x:c',NS):
            v=c.find('x:v',NS); raw=v.text if v is not None else ''
            value=strings[int(raw)] if c.get('t')=='s' and raw else raw
            if c.get('t')=='inlineStr':value=''.join(t.text or '' for t in c.findall('.//x:t',NS))
            style=xfs[int(c.get('s','0'))]; font=fonts[int(style.get('fontId','0'))]
            f=c.find('x:f',NS)
            cells[c.get('r')]={'value':value,'formula':f.text if f is not None else None,
                'styleId':int(c.get('s','0')),'style':xml_data(style),'font':xml_data(font),
                'alignment':dict(style.find('x:alignment',NS).attrib) if style.find('x:alignment',NS) is not None else {}}
        names={n.get('name'):n.text for n in wb.findall('x:definedNames/x:definedName',NS)}
        vml=[];effects=[]; media={}
        for name in archive.namelist():
            if name.endswith('.vml'):
                root=ET.fromstring(archive.read(name))
                for cd in root.findall('.//excel:ClientData',NS):
                    f=cd.find('excel:FmlaPict',NS)
                    if f is not None:vml.append({'sourceRange':f.text,'anchor':cd.find('excel:Anchor',NS).text})
            if name.startswith('xl/drawings/') and name.endswith('.xml'):
                root=ET.fromstring(archive.read(name))
                for change in root.findall('.//a:clrChange',NS):effects.append({'part':name,'effect':xml_data(change)})
            if name.startswith('xl/media/'):
                media[Path(name).name]=archive.read(name)
        return {'sheet':sheet_name,'definedNames':names,'cells':cells,
            'merges':[m.get('ref') for m in sheet.findall('x:mergeCells/x:mergeCell',NS)],
            'rows':[dict(r.attrib) for r in sheet.findall('x:sheetData/x:row',NS)],
            'columns':[dict(c.attrib) for c in sheet.findall('x:cols/x:col',NS)],
            'styles':xml_data(styles),'pageSetup':xml_data(sheet.find('x:pageSetup',NS)),
            'pageMargins':xml_data(sheet.find('x:pageMargins',NS)),
            'camera':vml,'assetEffects':effects},media


def source_draft(facts):
    cells=facts['cells']; val=lambda a:cells[a]['value']
    issue=(datetime(1899,12,30)+timedelta(days=float(val('K5')))).date().isoformat()
    items=[]
    for i in range(3):
        r=14+i
        if cells.get(f'B{r}',{}).get('value'):
            items.append({'id':f'item-{i+1}','name':val(f'B{r}'),'spec':cells.get(f'C{r}',{}).get('value',''),
                'unit':cells.get(f'D{r}',{}).get('value',''),'qty':float(val(f'E{r}')),
                'unitPrice':int(float(val(f'F{r}'))),'note':cells.get(f'H{r}',{}).get('value','')})
    return {'schemaVersion':1,'meta':{'quoteNo':val('K4'),'issueDate':issue,'validDays':7,
        'source':'saved-quote-skill','projectName':val('K9')},
        'sender':{'company':val('P6'),'rep':re.sub(r'\s+','',val('K6')),'contactPerson':re.sub(r'\s+','',val('K6')),
                  'bizNo':re.sub(r'\s+','',val('P4')),'address':val('P7').splitlines()[0].strip(),
                  'phone':val('M6'),'email':'','presetId':'cgi-source'},
        'recipient':{'company':val('K7'),'person':'','address':'','email':''},
        'items':items,'tax':{'mode':'EXCLUSIVE','rate':0.1},'memo':''}


def build_slots(draft, changes=None, node=DEFAULT_NODE):
    result=subprocess.run([str(node),str(HERE/'slots.cjs')],input=json.dumps({'draft':draft,'changes':changes or {}},ensure_ascii=False),
        text=True,encoding='utf-8',capture_output=True)
    if result.returncode:raise ValueError(result.stderr.strip().splitlines()[0:4])
    return json.loads(result.stdout)


def cmap(font):
    # Bounded profile accepts the simple embedded two-byte CMaps this source uses.
    # Reject other syntax instead of inferring a font substitution.
    raw=font['/ToUnicode'].get_data().decode('ascii'); mapping={}
    for block in re.findall(r'beginbfchar(.*?)endbfchar',raw,re.S):
        for a,b in re.findall(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>',block):mapping[int(a,16)]=bytes.fromhex(b).decode('utf-16-be')
    for block in re.findall(r'beginbfrange(.*?)endbfrange',raw,re.S):
        if '[' in block:raise ValueError('Array CMap ranges are outside this source profile')
        for a,b,c in re.findall(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>',block):
            for k in range(int(a,16),int(b,16)+1):mapping[k]=chr(int(c,16)+k-int(a,16))
    return mapping


def multiply(a,b):
    # Same row-vector PDF matrix convention used by pypdf's extraction.
    return [a[0]*b[0]+a[1]*b[2],a[0]*b[1]+a[1]*b[3],a[2]*b[0]+a[3]*b[2],a[2]*b[1]+a[3]*b[3],a[4]*b[0]+a[5]*b[2]+b[4],a[4]*b[1]+a[5]*b[3]+b[5]]


def point(cm,x,y):return (x*cm[0]+y*cm[2]+cm[4],x*cm[1]+y*cm[3]+cm[5])


def serialize(args,op):
    buffer=BytesIO()
    for arg in args:arg.write_to_stream(buffer);buffer.write(b' ')
    buffer.write(op+b'\n')
    return buffer.getvalue()


def pdf_program(reader):
    page=reader.pages[0]; fonts=page['/Resources']['/Font']; maps={n:cmap(f.get_object()) for n,f in fonts.items()}
    names={n:str(f.get_object()['/BaseFont']).split('+')[-1].lstrip('/') for n,f in fonts.items()}
    widths={}
    for key,font in fonts.items():
        descendant=font.get_object()['/DescendantFonts'][0].get_object();ws={};array=descendant.get('/W',[]);i=0
        while i<len(array):
            start=int(array[i]);i+=1
            if isinstance(array[i],list):
                for j,w in enumerate(array[i]):ws[start+j]=float(w)
                i+=1
            else:
                end=int(array[i]);w=float(array[i+1]);i+=2
                for j in range(start,end+1):ws[j]=w
        widths[key]=(ws,float(descendant.get('/DW',1000)))
    ops=ContentStream(page['/Contents'],reader).operations
    state={'cm':[1,0,0,1,0,0],'clip':[0,0,float(page.mediabox.width),float(page.mediabox.height)],'renderMode':0,'strokeWidth':1}
    stack=[]; path=[]; path_start=0; runs=[]; lines=[]; active=None; buffer=BytesIO(); insertion=None; previous_q=None
    height=float(page.mediabox.height)
    for i,(args,op) in enumerate(ops):
        offset=buffer.tell()
        if op==b'q':
            if not stack:previous_q=offset
            stack.append(copy.deepcopy(state))
        elif op==b'Q':state=stack.pop()
        elif op==b'cm':state['cm']=multiply([float(x) for x in args],state['cm'])
        elif op in (b'm',b'l'):
            if op==b'm':path_start=offset
            path.append(point(state['cm'],float(args[0]),float(args[1])))
        elif op==b're':
            x,y,w,h=map(float,args);path=[point(state['cm'],x,y),point(state['cm'],x+w,y+h)]
        elif op in (b'W',b'W*') and path:
            p=[min(x for x,y in path),min(y for x,y in path),max(x for x,y in path),max(y for x,y in path)]
            c=state['clip'];state['clip']=[max(c[0],p[0]),max(c[1],p[1]),min(c[2],p[2]),min(c[3],p[3])]
        elif op in (b'n',b'S',b's',b'f',b'f*',b'B',b'B*'):
            if op==b'S' and len(path)==2 and abs(path[0][1]-path[1][1])<0.00001:
                lines.append({'start':path_start,'end':offset+len(serialize(args,op)),
                    'points':path[:],'widthPt':state['strokeWidth']*abs(state['cm'][0])})
            path=[]
        elif op==b'w':state['strokeWidth']=float(args[0])
        elif op==b'Tr':state['renderMode']=int(args[0])
        elif op==b'BT':
            active={'start':offset,'index':len(runs),'text':'','seq':[],'cm':state['cm'][:],
                'clipPdf':state['clip'][:],'renderMode':state['renderMode'],'strokeWidth':state['strokeWidth'],'advanceLogical':0}
        if active is not None:
            if op==b'Tf':active['fontKey']=str(args[0]);active['family']=names[args[0]];active['size']=float(args[1])
            elif op==b'Tm':active['tm']=[float(x) for x in args]
            elif op==b'Tr':active['renderMode']=int(args[0])
            elif op in (b'TJ',b'Tj'):
                for s in (args[0] if op==b'TJ' else [args[0]]):
                    if isinstance(s,(ByteStringObject,TextStringObject)):
                        raw=s.original_bytes
                        if len(raw)%2:raise ValueError('Unexpected single-byte source font')
                        text=''.join(maps[active['fontKey']][int.from_bytes(raw[j:j+2],'big')] for j in range(0,len(raw),2))
                        active['text']+=text;active['seq'].append(text)
                        ws,dw=widths[active['fontKey']]
                        active['advanceLogical']+=sum(ws.get(int.from_bytes(raw[j:j+2],'big'),dw) for j in range(0,len(raw),2))*active['size']/1000
                    else:
                        active['seq'].append(float(s));active['advanceLogical']-=float(s)*active['size']/1000
        buffer.write(serialize(args,op))
        if op==b'ET':
            active['end']=buffer.tell()
            c=active['clipPdf'];active['bbox']=[c[0],height-c[3],c[2],height-c[1]]
            runs.append(active);active=None
        if op==b'Do' and insertion is None:
            insertion=previous_q
    if stack or active is not None:raise ValueError('Unbalanced source drawing program')
    return buffer.getvalue(),runs,insertion,lines


def compact(text):return re.sub(r'\s+','',str(text))


def compile_profile(xlsx,pdf,out,node=DEFAULT_NODE):
    out=Path(out)
    if out.exists() and any(out.iterdir()):raise ValueError('Compile into an empty new template directory')
    out.mkdir(parents=True,exist_ok=True)
    facts,media=workbook_facts(xlsx)
    if not any(c['sourceRange']=='$J$4:$R$9' for c in facts['camera']):raise ValueError('CGI live camera source not found')
    reader=PdfReader(pdf)
    if len(reader.pages)!=1:raise ValueError('This profile requires exactly one source page')
    program,runs,insertion,lines=pdf_program(reader)
    if len(runs)!=140 or insertion is None:raise ValueError('Unrecognized CGI source print program')
    built=build_slots(source_draft(facts),node=node)
    # This source-specific onboarding map is verified against source live cells.
    # It is compiler metadata, never literal content or CSS offset calibration.
    definitions=[('quoteNo','K4',[109],'left'),('issueDate','K5',[114],'date'),
        ('recipient','K7',[124],'left'),('project','K9',[136],'left'),
        ('project','B13',[24,25,26],'left'),('grandWrittenLine','A11',list(range(3,11)),'left'),
        ('subtotal','G22',[51],'right'),('vat','G23',[55],'right'),('grand','G24',[59],'right')]
    item_runs={0:{'Name':[28],'Unit':[29],'Qty':[31],'UnitPrice':[33],'Amount':[35]},1:{'Amount':[38]},2:{'Amount':[41]}}
    for i,fields in item_runs.items():
        for field,ids in fields.items():
            col={'Name':'B','Unit':'D','Qty':'E','UnitPrice':'F','Amount':'G'}[field]
            definitions.append((f'item{i}{field}',f'{col}{14+i}',ids,'right' if field in ('UnitPrice','Amount') else 'center' if field in ('Unit','Qty') else 'left'))
    bindings=[]
    for key,cell,ids,align in definitions:
        rs=[runs[j] for j in ids];expected=built['slots'][key]
        observed=''.join(r['text'] for r in rs)
        if compact(observed)!=compact(expected):raise ValueError(f'Source value mismatch at {cell}: {key}')
        first=rs[0];sty=facts['cells'][cell]
        binding={'key':key,'cell':cell,'runIndices':ids,'original':expected,'align':align,'runs':rs,
            'bbox':first['bbox'],'sourceAlignment':sty['alignment'],'family':first['family'],
            'cm':first['cm'],'tm':first['tm'],'size':first['size'],'renderMode':first['renderMode'],
            'strokeWidth':first['strokeWidth'],'shrink':sty['alignment'].get('shrinkToFit')=='1',
            'sourceFont':sty['font'],'sourceFormula':sty['formula']}
        # A shrunk camera cell reverts to nominal 13-logical-unit font for short values.
        binding['nominalSize']=13.0 if cell in ('K7','K9') else first['size']
        origin=point(first['cm'],first['tm'][4],first['tm'][5])
        binding['rightAnchorPt']=origin[0]+first['advanceLogical']*abs(first['cm'][0])
        if cell=='K4':
            candidates=[line for line in lines if first['end']<line['start']<first['end']+250 and abs(line['points'][0][0]-origin[0])<0.001]
            if len(candidates)!=1:raise ValueError('Source quote-number underline could not be bound')
            binding['underline']=candidates[0]
            binding['underline']['extensionPt']=candidates[0]['points'][1][0]-binding['rightAnchorPt']
        bindings.append(binding)
    # Blank fields have independent source-grid slots. They never move table rows.
    # Coordinates are obtained from existing printed cell clips, not guessed CSS.
    rows={i:runs[35 if i==0 else 38 if i==1 else 41]['bbox'] for i in range(3)}
    grid={}
    for field,index in {'Name':28,'Unit':29,'Qty':31,'UnitPrice':33,'Amount':35}.items():grid[field]=runs[index]['bbox']
    # C and H were blank in the original. Their boundaries are the adjacent native clips.
    grid['Spec']=[grid['Name'][2],0,grid['Unit'][0],0]
    grid['Note']=[grid['Amount'][2],0,572.692,0]
    for i in range(3):
        for field in ('Name','Spec','Unit','Qty','UnitPrice','Amount','Note'):
            key=f'item{i}{field}'
            if any(b['key']==key for b in bindings):continue
            bbox=[grid[field][0],rows[i][1],grid[field][2],rows[i][3]]
            # Name cell in row14 has no merge. Each row uses the same column grid.
            ref=runs[28 if field in ('Name','Spec','Note') else 29 if field=='Unit' else 31 if field=='Qty' else 33]
            baseline_top=(point(ref['cm'],ref['tm'][4],ref['tm'][5])[1])
            baseline_top=841-baseline_top+(rows[i][1]-rows[0][1])
            x=bbox[0]+(point(ref['cm'],ref['tm'][4],ref['tm'][5])[0]-ref['bbox'][0])
            local_x=(x-ref['cm'][4])/ref['cm'][0];local_y=(841-baseline_top-ref['cm'][5])/ref['cm'][3]
            anchor_ref=runs[33 if field=='UnitPrice' else 35]
            anchor=point(anchor_ref['cm'],anchor_ref['tm'][4],anchor_ref['tm'][5])[0]+anchor_ref['advanceLogical']*abs(anchor_ref['cm'][0])
            right_anchor=bbox[2]-(anchor_ref['bbox'][2]-anchor)
            bindings.append({'key':key,'cell':{'Name':'B','Spec':'C','Unit':'D','Qty':'E','UnitPrice':'F','Amount':'G','Note':'H'}[field]+str(14+i),
                'runIndices':[],'runs':[],'original':built['slots'][key],'align':'right' if field in ('UnitPrice','Amount') else 'center' if field in ('Unit','Qty') else 'left',
                'bbox':bbox,'family':ref['family'],'cm':ref['cm'],'tm':[1,0,0,-1,local_x,local_y],
                'size':ref['size'],'nominalSize':ref['size'],'renderMode':0,'strokeWidth':1,'shrink':False,
                'rightAnchorPt':right_anchor,
                'sourceAlignment':facts['cells'].get({'Name':'B','Spec':'C','Unit':'D','Qty':'E','UnitPrice':'F','Amount':'G','Note':'H'}[field]+str(14+i),{}).get('alignment',{})})
    # Store only resource objects in a blank PDF. No source content stream is retained here.
    writer=PdfWriter();page=writer.add_blank_page(float(reader.pages[0].mediabox.width),float(reader.pages[0].mediabox.height))
    page[NameObject('/Resources')]=reader.pages[0]['/Resources'].clone(writer)
    with (out/'resources.pdf').open('wb') as f:writer.write(f)
    (out/'program.zlib').write_bytes(zlib.compress(program,9))
    for name,data in media.items():
        (out/'provenance').mkdir(exist_ok=True);(out/'provenance'/name).write_bytes(data)
    font_files={'Gulim':'gulim.ttc','GulimChe':'gulim.ttc','MalgunGothic':'malgun.ttf','MalgunGothicBold':'malgunbd.ttf'}
    font_sources={family:{'file':name,'sha256':digest(Path('C:/Windows/Fonts')/name)} for family,name in font_files.items()}
    template={'schemaVersion':1,'templateId':'cgi-220621-source-vector-v1','kind':'source-derived-editable-quote',
        'sourceHashes':{'xlsx':digest(xlsx),'pdf':digest(pdf)},'sources':{'xlsx':Path(xlsx).name,'pdf':Path(pdf).name},
        'page':{'widthPt':float(page.mediabox.width),'heightPt':float(page.mediabox.height),'count':1},
        'renderer':{'name':'compiled-pdf-display-program','version':1,'runtimeSourceAccess':False,
                    'programSha256':sha256(program).hexdigest(),'resourceSha256':digest(out/'resources.pdf'),'insertion':insertion,
                    'cameraAuthority':'live XLSX J4:R9 cells/styles/merges; PDF operators are observed print renderer metadata',
                    'cameraRasterized':False,'layering':'text/grid before source logo and seal'},
        'workbook':facts,'draft':built['draft'],'originalTotals':built['totals'],'bindings':bindings,
        'fontSources':font_sources,
        'supportedFields':['recipient','project','subtotal','issueDate','quoteNo','items'],
        'supportedItemCount':{'minimum':1,'maximum':3,'rowHeightChanges':False},
        'certification':{'status':'UNVERIFIED','toleranceAssumed':False}}
    write_json(out/'template.json',template)
    return template


def n(value):return ('%.9f'%float(value)).rstrip('0').rstrip('.') or '0'


def parse_request(text):
    """A bounded labelled Korean edit grammar; never guesses unmentioned fields."""
    fields={'제출처':'recipient','수신처':'recipient','건명':'project','공사명':'project',
            '공급가액':'subtotal','견적번호':'quoteNo','작성일자':'issueDate','작성일':'issueDate'}
    pattern=r'('+'|'.join(fields)+r')\s*(?:을|를|은|는|:)?\s*'
    matches=list(re.finditer(pattern,text))
    if not matches or text[:matches[0].start()].strip(' \t\r\n"\''):
        raise ValueError('Use labelled edits: 제출처, 건명, 공급가액, 작성일자, 견적번호')
    changes={}
    for i,match in enumerate(matches):
        raw=text[match.end():matches[i+1].start() if i+1<len(matches) else len(text)].strip(' ,\n\r\t')
        raw=re.sub(r'(?:으?로)?\s*(?:바꾸고|바꿔줘|바꿔|변경해줘|변경하고|해줘|해주세요|해\s*줘)\s*[,。.]*$','',raw).strip(' ,\n\r\t"\'')
        if raw.endswith('.'):raw=raw[:-1].rstrip()
        key=fields[match.group(1)]
        if not raw or key in changes:raise ValueError(f'Ambiguous or empty {match.group(1)}')
        if key=='issueDate':
            date=re.fullmatch(r'(\d{4})\s*(?:년|[-/.])\s*(\d{1,2})\s*(?:월|[-/.])\s*(\d{1,2})\s*일?',raw)
            if not date:raise ValueError('작성일자는 YYYY-MM-DD 또는 YYYY년 MM월 DD일로 입력하세요')
            raw=f'{int(date[1]):04d}-{int(date[2]):02d}-{int(date[3]):02d}'
        changes[key]=raw
    return changes


def text_operator(text,metrics,size,source_seq=None):
    if source_seq is not None:
        # Dates preserve the vector year/month/day labels and their original gaps.
        pos=0;parts=[]
        for part in source_seq:
            if isinstance(part,str):
                current=text[pos:pos+len(part)];pos+=len(part);parts.append('<'+metrics.encode(current).hex()+'>')
            else:parts.append(n(part))
        if pos!=len(text):raise ValueError('Date digit layout mismatch')
        return '['+' '.join(parts)+'] TJ\n'
    return '<'+metrics.encode(text).hex()+'> Tj\n'


def render_profile(template_path,output,changes=None,node=DEFAULT_NODE):
    template_path=Path(template_path);template=json.loads((template_path/'template.json').read_text(encoding='utf-8'))
    built=build_slots(template['draft'],changes,node)
    program=zlib.decompress((template_path/'program.zlib').read_bytes())
    if sha256(program).hexdigest()!=template['renderer']['programSha256'] or digest(template_path/'resources.pdf')!=template['renderer']['resourceSha256']:
        raise ValueError('Compiled template integrity mismatch')
    reader=PdfReader(template_path/'resources.pdf');writer=PdfWriter();writer.add_page(reader.pages[0]);page=writer.pages[0]
    changed=[b for b in template['bindings'] if built['slots'][b['key']]!=b['original']]
    fonts={}
    for family in sorted({b['family'] for b in changed if built['slots'][b['key']]}):
        text=''.join(built['slots'][b['key']] for b in changed if b['family']==family)
        ref,metrics=embed_font(writer,family,text)
        if template.get('fontSources',{}).get(family,{}).get('sha256')!=metrics.source_sha256:
            raise ValueError(f'Installed {family} differs from the certified font; re-certification is required')
        key='/Edit'+str(len(fonts)+1);page['/Resources']['/Font'][NameObject(key)]=ref;fonts[family]=(key,metrics)
    removals=[];dynamic=[];layouts=[]
    for binding in changed:
        for run in binding['runs']:removals.append((run['start'],run['end']))
        if binding.get('underline'):removals.append((binding['underline']['start'],binding['underline']['end']))
        text=built['slots'][binding['key']]
        bbox=binding['bbox'];cm=binding['cm'];tm=binding['tm'][:]
        if not text:
            layouts.append({'key':binding['key'],'cell':binding['cell'],'bbox':bbox,'text':'','visible':False});continue
        font_key,metrics=fonts[binding['family']]
        size=binding['nominalSize'];sx=abs(cm[0]);sy=abs(cm[3]);width=metrics.width(text)*size*sx
        source_origin=point(cm,tm[4],tm[5])
        source_inset=max(0,source_origin[0]-bbox[0])
        available=max(0,bbox[2]-bbox[0]-2*source_inset)
        # Preserve native shrink-to-fit, never distort horizontal glyph geometry.
        if binding['shrink'] and width>available:
            size*=available/width;width=available
        original_point=point(cm,tm[4],tm[5]);x=original_point[0]
        if binding['align']=='right':x=binding['rightAnchorPt']-width
        elif binding['align']=='center':x=(bbox[0]+bbox[2]-width)/2
        if binding['key']!='issueDate' and not binding['shrink'] and width>bbox[2]-x-0.5:
            # Native non-shrinking cells would clip. Refuse a misleading completed output.
            raise ValueError(f"Text exceeds source cell {binding['cell']}; shorten {binding['key']} (native cell does not shrink)")
        tm[4]=(x-cm[4])/cm[0]
        if binding['shrink'] and size!=binding['size']:
            # Preserve measured baseline displacement per font size around the native cell center.
            center=(bbox[1]+bbox[3])/2
            baseline_top=template['page']['heightPt']-original_point[1]
            changed_top=center+(baseline_top-center)*size/binding['size']
            tm[5]=(template['page']['heightPt']-changed_top-cm[5])/cm[3]
        w=template['page']['widthPt'];h=template['page']['heightPt']
        ops='q\n'+f'{n(bbox[0])} {n(h-bbox[3])} {n(bbox[2]-bbox[0])} {n(bbox[3]-bbox[1])} re W n\n'
        ops+=' '.join(n(v) for v in cm)+' cm\n0 g 0 G\n'+n(binding['strokeWidth'])+' w\n'
        ops+='BT\n'+f'{font_key} {n(size)} Tf\n'+str(binding['renderMode'])+' Tr\n'+' '.join(n(v) for v in tm)+' Tm\n'
        ops+=text_operator(text,metrics,size,binding['runs'][0]['seq'] if binding['align']=='date' else None)+'ET\nQ\n'
        if binding.get('underline'):
            underline=binding['underline'];y=underline['points'][0][1]
            ops+='q\n0 G\n'+n(underline['widthPt'])+' w\n'+f'{n(x)} {n(y)} m {n(x+width+underline["extensionPt"])} {n(y)} l S\nQ\n'
        dynamic.append(ops.encode('ascii'))
        layouts.append({'key':binding['key'],'cell':binding['cell'],'bbox':bbox,'text':text,
            'fontFamily':binding['family'],'fontSizeLogical':size,'fontSizePt':size*sy,'widthPt':width,
            'sourceShrinkToFit':binding['shrink'],'visible':True})
    chunks=[];pos=0;insertion=template['renderer']['insertion'];inserted=False
    for start,end in sorted(removals):
        if start<pos:raise ValueError('Overlapping field bindings')
        if not inserted and pos<=insertion<=start:
            chunks.extend([program[pos:insertion],b''.join(dynamic),program[insertion:start]]);inserted=True
        else:chunks.append(program[pos:start])
        chunks.append(b'BT\nET\n');pos=end
    if not inserted:chunks.extend([program[pos:insertion],b''.join(dynamic),program[insertion:]])
    else:chunks.append(program[pos:])
    content=DecodedStreamObject();content.set_data(b''.join(chunks));page[NameObject('/Contents')]=writer._add_object(content.flate_encode())
    writer.add_metadata({'/Title':'견적서','/Producer':'B66 compiled source quote template v1'})
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('wb') as f:writer.write(f)
    instance={'templateId':template['templateId'],'templateManifestHash':digest(template_path/'template.json'),
        'pdfSha256':digest(output),'changes':changes or {},'draft':built['draft'],'totals':built['totals'],
        'changedBindings':layouts,'runtimeSourceAccess':False,'fontMetadata':{k:v[1].metadata for k,v in fonts.items()}}
    write_json(output.with_suffix('.instance.json'),instance)
    return instance


def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='command',required=True)
    c=s.add_parser('compile');c.add_argument('--xlsx',required=True);c.add_argument('--pdf',required=True);c.add_argument('--out',required=True)
    r=s.add_parser('render');r.add_argument('--template',required=True);r.add_argument('--out',required=True);r.add_argument('--changes')
    r.add_argument('--recipient');r.add_argument('--project');r.add_argument('--subtotal');r.add_argument('--date');r.add_argument('--quote-no');r.add_argument('--request')
    a=p.parse_args()
    if a.command=='compile':
        t=compile_profile(a.xlsx,a.pdf,a.out);print(json.dumps({'templateId':t['templateId'],'bindingCount':len(t['bindings']),'state':'UNVERIFIED'}))
    else:
        changes=json.loads(Path(a.changes).read_text(encoding='utf-8-sig')) if a.changes else {}
        if a.request:
            if changes:raise ValueError('Use --request or --changes, not both')
            changes=parse_request(a.request)
        for field,value in [('recipient',a.recipient),('project',a.project),('subtotal',a.subtotal),('issueDate',a.date),('quoteNo',a.quote_no)]:
            if value is not None:changes[field]=value
        instance=render_profile(a.template,a.out,changes)
        print(json.dumps({'pdf':str(Path(a.out).resolve()),'subtotal':instance['totals']['subtotal'],'vat':instance['totals']['vat'],'grand':instance['totals']['grand'],'changedBindings':len(instance['changedBindings'])},ensure_ascii=False))


if __name__=='__main__':main()
