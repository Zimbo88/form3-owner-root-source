import calendar,datetime,json,subprocess,unittest
from pathlib import Path
from zoneinfo import ZoneInfo

class LocalClock(unittest.TestCase):
    def test_german_wall_time_and_dst_boundaries(self):
        root=Path(__file__).resolve().parents[1]
        fragment=(root/'owner-ui/native/idle-clock.qmlinc').read_text()
        source=fragment[fragment.index('function ownerClockAppend'):]
        cases=[]
        for year in range(2020,2038):
            dates=[datetime.datetime(year,m,15,tzinfo=datetime.timezone.utc) for m in range(1,13)]
            for month in (3,10):
                day=calendar.monthrange(year,month)[1]
                while datetime.date(year,month,day).weekday()!=6:day-=1
                boundary=datetime.datetime(year,month,day,1,tzinfo=datetime.timezone.utc)
                dates.extend(boundary+datetime.timedelta(seconds=x) for x in (-61,-1,0,1,61))
            cases.extend([int(d.timestamp()*1000),'Idle '+d.astimezone(ZoneInfo('Europe/Berlin')).strftime('%d.%m.%y %H:%M')] for d in dates)
        code=source+'\nlet ownerClockEpochMs;for(const [ms,want] of '+json.dumps(cases)+'){ownerClockEpochMs=ms;const got=ownerClockAppend("Idle",true);if(got!==want)throw Error(JSON.stringify({ms,got,want}));}'
        code+='\nfor(const t of [0,NaN,Infinity,2208988800000]){ownerClockEpochMs=t;if(ownerClockAppend("Idle",true)!=="Idle time unavailable")throw Error("Invalid time accepted");}'
        result=subprocess.run(['node','-e',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        self.assertEqual(len(cases),396);self.assertEqual(result.returncode,0,result.stderr.decode())

    def test_ready_idle_custom_and_active_state_binding(self):
        from sys import path
        root=Path(__file__).resolve().parents[1]
        path.insert(0,str(root/'tools'))
        from build_native_clock_review import REPLACEMENT
        fragment=(root/'owner-ui/native/idle-clock.qmlinc').read_text()
        source=fragment[fragment.index('function ownerClockAppend'):]
        cases=[
          [False,False,'Ready','', 'Ready 14.09.26 10:00'],
          [False,False,'Idle','', 'Idle 14.09.26 10:00'],
          [True,False,'Printing','', 'Printing 14.09.26 10:00'],
          [True,False,'Paused','', 'Paused'],
          [True,False,'Pausing','', 'Pausing'],
          [True,False,'Printing','Important warning', 'Important warning'],
          [False,True,'Ready','', 'Ready'],
          [False,False,'Ready','Important warning', 'Important warning']]
        code=source+'\nlet ownerClockEpochMs=Date.UTC(2026,8,14,8);\n'
        code+='for(const [active,starting,status,custom,want] of '+json.dumps(cases)+'){\n'
        code+='const atomWatcher={activeAtom:active?{isPrintPausing:status==="Pausing",isPaused:status==="Paused"}:null};const orchestrator={isStartingPrint:starting};const model={text_headerSubtitle:custom};const PrinterStatusHelper={getLongPrinterStatus:()=>status};\n'
        code+='const got=('+REPLACEMENT+');if(got!==want)throw Error(JSON.stringify({got,want}));}'
        r=subprocess.run(['node','-e',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10)
        self.assertEqual(r.returncode,0,r.stderr.decode())

if __name__=='__main__':unittest.main()
