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


def test_fragmented_doorway_track_keeps_original_event():
    tracker = Tracker()
    for now in range(3):
        events = tracker.update([detection(x=.30)], now, [])
    original = tracker.tracks[events[0]['track_id']]
    original.event_id = 'original'

    # A brief gap and a jump large enough to start another track.
    assert tracker.update([], 3, []) == []
    for now in range(4, 7):
        assert tracker.update([detection(x=.48)], now, []) == []
    assert [(track.event_id, track.last) for track in tracker.tracks.values()] == [('original', 6)]


def test_nearby_people_who_overlap_in_time_keep_separate_events():
    tracker = Tracker()
    for now in range(3):
        tracker.update([detection(x=.30)], now, [])
    for now in range(3, 6):
        events = tracker.update([detection(x=.30), detection(x=.48)], now, [])
    assert len(events) == 1
    assert events[0]['box'] == detection(x=.48)['box']


def test_return_after_gap_can_alert_again():
    tracker = Tracker()
    for now in range(3):
        tracker.update([detection(x=.30)], now, [])
    for now in range(6, 9):
        events = tracker.update([detection(x=.48)], now, [])
    assert len(events) == 1


def test_ignore_box_matches_only_its_label_location_and_size():
    from watchyard.rules import ignored_box

    camera = {'ignore_boxes': {'person': [[.87, .12, .95, .41]]}}
    assert ignored_box('person', [.88, .13, .94, .40], camera)
    assert not ignored_box('cat', [.88, .13, .94, .40], camera)
    assert not ignored_box('person', [.70, .13, .76, .40], camera)
    assert not ignored_box('person', [.88, .22, .91, .32], camera)
    assert not ignored_box('person', [.88, .13, .94, .40], {})
