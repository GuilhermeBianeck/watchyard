from watchyard.rules import Tracker,inside


def detection(label='person',x=0.2,score=.8):
    return {'label':label,'confidence':score,'box':[x,.2,x+.1,.7]}


def test_brief_false_positive_does_not_alert():
    tracker=Tracker()
    assert tracker.update([detection()],0,[])==[]
    assert tracker.update([],1,[])==[]
    assert tracker.update([],4,[])==[]


def test_confirmed_visit_alerts_once():
    t=Tracker()
    assert t.update([detection()],0,[])==[]
    assert t.update([detection()],.5,[])==[]
    assert len(t.update([detection()],1,[]))==1
    assert t.update([detection(x=.25)],1.5,[])==[]


def test_parked_car_not_realerted_by_leaf_motion():
    t=Tracker()
    for i in range(20):
        assert not t.update([detection('car',x=.2+(i%2)*.002)],i/2,[])
    assert len(t.update([detection('car',x=.25)],10,[]))==1
    assert not t.update([detection('car',x=.26)],10.5,[])


def test_two_people_each_alert_independently():
    t=Tracker()
    for now in (0,.5):
        assert not t.update([detection(x=.1),detection(x=.7)],now,[])
    assert len(t.update([detection(x=.1),detection(x=.7)],1,[]))==2


def test_zone_uses_feet_and_repeated_inside_observations():
    zone=[[.5,.5],[1,.5],[1,1],[.5,1]]
    t=Tracker()
    for now in (0,.5,1):
        assert not t.update([detection(x=.4)],now,zone)
    for now in (1.5,2):
        assert not t.update([detection(x=.49)],now,zone)
    assert len(t.update([detection(x=.49)],2.5,zone))==1


def test_stale_observations_cannot_confirm():
    t=Tracker()
    for now in (0,4,8):
        assert not t.update([detection()],now,[])


def test_occlusion_does_not_duplicate_alert():
    t=Tracker()
    for now in (0,.5,1):
        t.update([detection()],now,[])
    t.update([],3,[])
    assert not t.update([detection(x=.21)],5,[])


def test_polygon():
    assert inside((.5,.5),[])
    assert inside((.5,.5),[[0,0],[1,0],[1,1],[0,1]])
    assert not inside((.1,.1),[[.3,.3],[.8,.3],[.8,.8],[.3,.8]])
