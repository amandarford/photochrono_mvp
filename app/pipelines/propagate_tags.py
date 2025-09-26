def propagate_person(db, cluster_id, person_id):
    # set photo_tags(person) for all faces in this cluster
    # ensure duplicates get the label too with higher confidence

def propagate_date(db, photo_id, new_dt):
    # update duplicates
    # fill neighbors within window if missing/low confidence
