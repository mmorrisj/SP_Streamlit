def insert_event_name(initiating_country, recipient_country, event_name):
    existing_event = EventNames.query.filter_by(
        initiating_country=initiating_country,
        recipient_country=recipient_country,
        event_name=event_name
    ).first()
    
    if existing_event:
        print('Event name already exists:', event_name)
        return 
    else:
        print('Inserting new event name:', event_name)
        new_event = EventNames(
            initiating_country=initiating_country,
            recipient_country=recipient_country,
            event_name=event_name
        )
        db.session.add(new_event)
    db.session.commit()
        
def insert_event_names():
    fetched_events = db.session.query(Event).all()
    for event in fetched_events:
        initiating_country = event.initiating_country 
        recipient_country = event.recipient_country 
        event_name = event.event_name

        if initiating_country and recipient_country and event_name:
            insert_event_name(initiating_country, recipient_country, event_name)