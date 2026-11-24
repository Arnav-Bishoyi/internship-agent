from datetime import date
from .google import client
from ..duplicates import HEADERS,compare
from ..models import Job,Review

ACTION=("Agent ID","Company","Role","Link","Deadline","Next step","Possibly submitted","Decision")


class Sheets:
    def __init__(self,settings):
        self.api=client("sheets","v4").spreadsheets()
        self.book=settings["spreadsheet"]
        self.tab=settings.get("tab","Untitled")

    def values(self,tab,columns):
        name=tab.replace("'","''")
        return self.api.values().get(spreadsheetId=self.book,range=f"'{name}'!{columns}").execute().get("values",[])

    def rows(self):
        data=self.values(self.tab,"A:K")
        if not data or tuple(data[0])!=HEADERS:
            raise Review("Restore or remap the tracker header before submitting.")
        return [dict(zip(HEADERS,r)) for r in data[1:]]

    def check(self,job):
        return compare(job,self.rows())

    def append(self,tab,values):
        label=tab.replace("'","''")
        self.api.values().append(spreadsheetId=self.book,range=f"'{label}'!A:A",
            insertDataOption="INSERT_ROWS",valueInputOption="RAW",body={"values":[values]}).execute()

    def update(self,tab,entries):
        label=tab.replace("'","''")
        self.api.values().batchUpdate(spreadsheetId=self.book,body={"valueInputOption":"RAW",
            "data":[{"range":f"'{label}'!{cell}","values":[[value]]} for cell,value in entries]}).execute()

    def applied(self,payload):
        j=Job(**payload["job"])
        marker="Agent record: "+j.key
        rows=self.rows()
        if any(marker in r.get("Notes / Source","").splitlines() for r in rows): return
        check=compare(j,rows)
        if check.kind=="review":
            raise Review(f"Confirmed application. Reconcile tracker row {check.row} before writing its receipt.")
        if check.kind=="duplicate": return
        note="\n".join(filter(None,[marker,"Cycle: "+j.cycle,"Agent req: "+j.req if j.req else "",
                                     j.url,"Evidence: "+payload["evidence"],"Source: "+payload.get("sources","")]))
        if check.kind=="planned":
            row=check.row
            existing=rows[row-2].get("Notes / Source","")
            self.update(self.tab,[(f"D{row}",payload["date"]),(f"E{row}","Applied"),(f"K{row}",(existing+"\n"+note).strip())])
        else:
            self.append(self.tab,[j.company,j.title,j.location,payload["date"],"Applied","","","","","",""+note])

    def ensure_actions(self):
        meta=self.api.get(spreadsheetId=self.book,fields="sheets(properties(title))").execute()
        if not any(s["properties"]["title"]=="Needs Action" for s in meta["sheets"]):
            self.api.batchUpdate(spreadsheetId=self.book,body={"requests":[{"addSheet":{"properties":{"title":"Needs Action"}}}]}).execute()
        first=self.values("Needs Action","A1:H1")
        if not first:
            self.update("Needs Action",[(f"{chr(65+i)}1",v) for i,v in enumerate(ACTION)])
        elif tuple(first[0])!=ACTION: raise Review("Restore the Needs Action header.")

    def actions(self):
        data=self.values("Needs Action","A:H")
        if not data or tuple(data[0])!=ACTION: raise Review("Check Needs Action setup.")
        return [dict(zip(ACTION,row)) for row in data[1:]]

    def issue(self,key,p):
        rows=self.actions()
        vals=[key,p["company"],p["title"],p["url"],p["deadline"],p["reason"],"Yes" if p["uncertain"] else "No",""]
        for n,r in enumerate(rows,2):
            if r.get("Agent ID")==key:
                if r.get("Next step")!=p["reason"] or r.get("Decision") in ("Handled","Resolved — resume"):
                    self.update("Needs Action",[(f"{chr(65+i)}{n}",v) for i,v in enumerate(vals)])
                return
        self.append("Needs Action",vals)
