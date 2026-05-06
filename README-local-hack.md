# install

pipx install . --force 

strix -v

# Set the API key first
export ANTHROPIC_API_KEY="sk-ant-api-key"
export STRIX_LLM="anthropic/claude-sonnet-4-6"


# run 

strix  -t https://foo.bar.com \
    --instruction "Test using username=demo@account and password=password123" 


# 
