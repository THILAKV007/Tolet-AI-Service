import re


class TranslationCleaner:

    def clean(

        self,

        text: str
    ):

        text = text.lower()

        text = re.sub(

            r'\s+',

            ' ',

            text
        )


        text = text.replace(

            "2 bhk",

            "2bhk"
        )

        text = text.replace(

            "3 bhk",

            "3bhk"
        )

        text = text.replace(

            "1 bhk",

            "1bhk"
        )

        text = text.replace(

            "rs.",

            "₹"
        )

        text = text.replace(

            "rupees",

            "₹"
        )

        text = re.sub(

            r'[^\w\s₹]',

            ' ',

            text
        )

        text = re.sub(

            r'\s+',

            ' ',

            text
        ).strip()

        return text