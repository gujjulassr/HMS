use('dpms_v2_chat')

var temp=db.chat_messages.find({
    session_id:"d0000000-0000-0000-0000-000000000001"
})

temp.forEach(element => {
    print(Object.keys(element))
    
});