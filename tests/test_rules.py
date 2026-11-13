import numpy as np

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


def vehicle_scene(seed, x, brightness=0):
    rng = np.random.default_rng(seed)
    frame = np.full((240, 400, 3), 35 + brightness, dtype=np.uint8)
    patch = rng.integers(50, 170, (96, 80, 1), dtype=np.uint8) + brightness
    frame[72:168, x:x + 80] = patch
    return frame


def vehicle_detection(x):
    return {'label': 'car', 'box': [x / 400, .3, (x + 80) / 400, .7], 'confidence': .9}


def test_box_shift_during_lighting_change_does_not_alert():
    tracker = Tracker()
    for tick, (box, brightness) in enumerate(((80, 0), (80, 0), (102, 70), (102, 35), (80, 0))):
        assert not tracker.update([vehicle_detection(box)], tick, [], window=3.5,
                                  frame=vehicle_scene(1, 80, brightness))
    track, = tracker.tracks.values()
    assert track.moved_at is None


def test_motion_timestamp_does_not_advance_while_vehicle_is_parked():
    tracker = Tracker()
    alerts = []
    for tick, (car, box) in enumerate(((160, 160), (168, 168), (180, 180),
                                       (180, 188), (180, 180), (180, 180))):
        alerts.extend(tracker.update([vehicle_detection(box)], tick, [], window=3.5,
                                     frame=vehicle_scene(1, car)))
    assert len(alerts) == 1
    track, = tracker.tracks.values()
    assert track.last == 5
    assert track.moved_at == 2


def test_vehicle_reconnects_after_large_jump_only_if_patches_match():
    for seed in (1, 2):
        tracker = Tracker()
        for tick, x in enumerate((40, 51, 62)):
            alerts = tracker.update([vehicle_detection(x)], tick, [], window=3.5,
                                    frame=vehicle_scene(1, x))
        track_id = alerts[0]['track_id']
        tracker.update([], 3, [])
        for tick, x in enumerate((132, 143, 154), start=4):
            alerts = tracker.update([vehicle_detection(x)], tick, [], window=3.5,
                                    frame=vehicle_scene(seed, x))
        if seed == 1:
            assert not alerts
            assert tracker.tracks[track_id].last == 6
        else:
            assert len(alerts) == 1
            assert alerts[0]['track_id'] != track_id


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


def test_weak_person_detections_only_continue_a_confirmed_overlapping_track_briefly():
    tracker = Tracker()
    low = detection(x=.21, score=.38)
    for tick in range(3):
        assert not tracker.update([], tick, [], weak_people=[low])
    assert not tracker.tracks
    for tick in range(3, 6):
        alerts = tracker.update([detection()], tick, [], window=3.5)
    track = tracker.tracks[alerts[0]['track_id']]
    track.event_id = 'person'
    for tick in (6, 7, 8, 9):
        assert not tracker.update([], tick, [], weak_people=[low, detection(x=.75, score=.4)])
    assert len(tracker.tracks) == 1
    assert track.last == 8
    assert track.last_strong == 5
    assert len(track.observations) < 3


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
