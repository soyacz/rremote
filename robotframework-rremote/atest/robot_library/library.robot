*** Settings ***
Library    ../../src/RRemote.py    http://localhost:8000
*** Test Cases ***
Can Execute Keyword
    ${resp}    Msg    some test message
    Log    ${resp}    console=True
    
Can Execute Keyword datetime
    ${now}    Evaluate    datetime.datetime.now()    datetime
    ${resp}    Msg    ${now}
    Log    ${resp}    console=True

Can Fail
    Run Keyword And Expect Error    ValueError: Just Failing    Failing Cat    Just Failing

Can sleep
    [Documentation]    Run tests in parallel to see it RRemoteServer executes them in the same time
    Sleeping Cat    ${5}
