*** Settings ***
Library    RequestsLibrary
Library    Process
Suite Setup    Start Remote Instance Server And Connect To It
Suite Teardown    Clean Up

*** Test Cases ***
Can Get Keyword Names
    ${response}    Get On Session    remote_library    /get_keyword_names    headers=${HEADERS}
    Should Be Equal    ${response.status_code}    ${200}
    Should Be Equal    ${response.text}    ["msg","sleeping_cat"]

Can Get Keyword Documentation
    ${response}    Get On Session    remote_library    /get_keyword_documentation/?name\=msg    headers=${HEADERS}  
    Should Be Equal    ${response.status_code}    ${200}
    Should Be Equal    ${response.text}     "this is documentation for msg keyword"

Can Get Library Documentation
    ${response}    Get On Session    remote_library    /get_keyword_documentation/?name\=__intro__    headers=${HEADERS}  
    Should Be Equal    ${response.status_code}    ${200}
    Should Be Equal    ${response.text}     "this is nice intro of tested library"

Can Get Library Initialization Documentation
    ${response}    Get On Session    remote_library    /get_keyword_documentation/?name\=__init__    headers=${HEADERS}  
    Should Be Equal    ${response.status_code}    ${200}
    Should Be Equal    ${response.text}     "this is test description of library initialization"

Can Get Keyword Arguments
    ${response}    Get On Session    remote_library    /get_keyword_arguments/?name\=msg    headers=${HEADERS}  
    Should Be Equal    ${response.status_code}    ${200}
    Should Be Equal    ${response.text}     ["message"]


*** Keywords ***
Start Remote Instance Server And Connect To It
    Create Session    remote_library    http://127.0.0.1:8000
    ${response}    Get On Session    remote_library    /create_instance
    Log To Console    ${response.headers}
    ${HEADERS}    Create Dictionary    x-instance-id=${response.headers["x-instance-id"]}
    Set Suite Variable    ${HEADERS}    
    # Start Remote Library

Clean Up
    Terminate All Processes
    ${response}    Delete On Session    remote_library    /delete_instance    headers=${HEADERS}  

Start Remote Library
    Start Process    poetry     run     uvicorn     RemoteInstance.RemoteInstanceServer:app
    Wait Until Remote Instance Server Is Up

Wait Until Remote Instance Server Is Up
    Wait Until Keyword Succeeds    5s    0.5s    Get On Session    remote_library    /healthcheck
    